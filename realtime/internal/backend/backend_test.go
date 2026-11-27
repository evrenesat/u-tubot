package backend

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestFetchNamesTheLiveServerAndSendsSecretOnlyWhenSet(t *testing.T) {
	var gotClient, gotSecret string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotClient, gotSecret = r.Header.Get(ClientHeader), r.Header.Get(SecretHeader)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"user":"u","features":{"voice":true},"voice":{"enabled":true}}`))
	}))
	defer srv.Close()

	c := New(srv.URL, time.Second, 0)
	if _, err := c.Check(context.Background(), "utb_a"); err != nil {
		t.Fatal(err)
	}
	if gotClient != ClientName || gotSecret != "" {
		t.Fatalf("no secret configured: client=%q secret=%q", gotClient, gotSecret)
	}

	c = New(srv.URL, time.Second, 0).WithSecret("rt-secret")
	if _, err := c.Check(context.Background(), "utb_b"); err != nil {
		t.Fatal(err)
	}
	if gotClient != ClientName || gotSecret != "rt-secret" {
		t.Fatalf("secret configured: client=%q secret=%q", gotClient, gotSecret)
	}
}

func TestRedirectNeverCarriesTheSecret(t *testing.T) {
	var targetHits int
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		targetHits++
		w.WriteHeader(http.StatusOK)
	}))
	defer target.Close()
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL+"/v1/me", http.StatusTemporaryRedirect)
	}))
	defer origin.Close()

	c := New(origin.URL, time.Second, 0).WithSecret("rt-secret")
	if _, err := c.Check(context.Background(), "utb_c"); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("a redirect must be unavailable, got %v", err)
	}
	if targetHits != 0 {
		t.Fatalf("the redirect target was contacted %d times", targetHits)
	}
}
