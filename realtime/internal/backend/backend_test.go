package backend

import (
	"context"
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
