// utubot-rt is the live server of u·tubot's voice control (ai/VOICE_CONTROL_PLAN.md): one WebSocket per device,
// the focus store, target choice and command routing. Its entry point (flags, signal handling, graceful shutdown)
// is adapted from R2T4's server, MIT, see THIRD_PARTY.md.
//
//	utubot-rt serve -config /etc/utubot/realtime.toml
//	utubot-rt bench -n 3000 -max-p99 20ms
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/evrenesat/u-tubot/realtime/internal/backend"
	"github.com/evrenesat/u-tubot/realtime/internal/bench"
	"github.com/evrenesat/u-tubot/realtime/internal/config"
	"github.com/evrenesat/u-tubot/realtime/internal/session"
	"github.com/evrenesat/u-tubot/realtime/internal/stats"
	"github.com/evrenesat/u-tubot/realtime/internal/ws"
)

// Version is set with -ldflags at build time.
var Version = "dev"

const authCacheSplit = 4

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "serve":
		err = serve(os.Args[2:])
	case "bench":
		err = runBench(os.Args[2:])
	case "version":
		fmt.Println(Version)
	default:
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "utubot-rt:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: utubot-rt serve -config FILE | bench [-n N] [-max-p99 D] | version")
}

func serve(args []string) error {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	path := fs.String("config", "", "TOML configuration file")
	_ = fs.Parse(args)
	cfg, err := config.Load(*path, os.Getenv)
	if err != nil {
		return err
	}
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	client := backend.New(cfg.BackendURL, cfg.BackendTimeout, cfg.AuthCache/authCacheSplit)
	hub := session.New(session.Options{Config: cfg, Recorder: client, Stats: stats.New(cfg.StatsWindow), Log: log})
	srv := ws.New(cfg, hub, client, log)
	httpServer := &http.Server{Addr: cfg.Listen, Handler: srv.Handler(), ReadHeaderTimeout: cfg.HelloTimeout}
	log.Info("live server starting", "version", Version, "listen", cfg.Listen, "path", cfg.Path)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	failed := make(chan error, 1)
	go func() { failed <- httpServer.ListenAndServe() }()
	select {
	case err := <-failed:
		return err
	case <-ctx.Done():
	}
	log.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownGrace)
	defer cancel()
	srv.Shutdown(shutdownCtx)
	if err := httpServer.Shutdown(shutdownCtx); err != nil && !errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	hub.Wait()
	return nil
}

func runBench(args []string) error {
	fs := flag.NewFlagSet("bench", flag.ExitOnError)
	opts := bench.Default()
	fs.IntVar(&opts.Commands, "n", opts.Commands, "commands to send")
	fs.IntVar(&opts.Users, "users", opts.Users, "users, each with a screen and a controller")
	fs.IntVar(&opts.Idle, "idle", opts.Idle, "idle connected devices that only hold sockets")
	maxP99 := fs.Duration("max-p99", bench.DefaultMaxP99, "fail when the server's own time at the 99th percentile is over this")
	_ = fs.Parse(args)
	res, err := bench.Run(opts)
	if err != nil {
		return err
	}
	fmt.Print(res.Table())
	if res.Server.P99 > float64(maxP99.Microseconds())/1000 {
		return fmt.Errorf("server time p99 %.2f ms is over the budget of %s", res.Server.P99, *maxP99)
	}
	return nil
}
