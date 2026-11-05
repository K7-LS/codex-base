// Verify the GitHub-signed release statement without a GitHub account.
package main

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/sigstore/sigstore-go/pkg/bundle"
	"github.com/sigstore/sigstore-go/pkg/root"
	"github.com/sigstore/sigstore-go/pkg/verify"
)

const (
	releaseIdentity  = "https://dotcom.releases.github.com"
	releasePredicate = "https://in-toto.io/attestation/release/v0.2"
)

func run(args []string, output io.Writer) error {
	flags := flag.NewFlagSet("release-verifier", flag.ContinueOnError)
	bundlePath := flags.String("bundle", "", "GitHub release Sigstore bundle")
	rootPath := flags.String("trusted-root", "", "GitHub-only TUF-verified trusted root")
	commit := flags.String("commit", "", "Git release commit SHA-1")
	if err := flags.Parse(args); err != nil {
		return err
	}
	digest, err := hex.DecodeString(*commit)
	if err != nil || len(digest) != 20 || *bundlePath == "" || *rootPath == "" || flags.NArg() != 0 {
		return errors.New("bundle, trusted root and 40-digit release commit are required")
	}

	trustedRoot, err := root.NewTrustedRootFromPath(*rootPath)
	if err != nil {
		return fmt.Errorf("load trusted root: %w", err)
	}
	if len(trustedRoot.TimestampingAuthorities()) == 0 || len(trustedRoot.RekorLogs()) != 0 {
		return errors.New("expected the GitHub Sigstore trusted root")
	}
	signed, err := bundle.LoadJSONFromPath(*bundlePath)
	if err != nil {
		return fmt.Errorf("load release bundle: %w", err)
	}
	verifier, err := verify.NewVerifier(trustedRoot, verify.WithSignedTimestamps(1))
	if err != nil {
		return err
	}
	// GitHub's release certificate has no Actions OIDC issuer extension.
	identity, err := verify.NewShortCertificateIdentity("", ".*", releaseIdentity, "")
	if err != nil {
		return err
	}
	result, err := verifier.Verify(signed, verify.NewPolicy(
		verify.WithArtifactDigest("sha1", digest),
		verify.WithCertificateIdentity(identity),
	))
	if err != nil {
		return fmt.Errorf("verify GitHub release signature: %w", err)
	}
	if result.Statement == nil || result.Statement.PredicateType != releasePredicate {
		return errors.New("expected the GitHub release predicate")
	}
	return json.NewEncoder(output).Encode(result)
}

func main() {
	if err := run(os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}
