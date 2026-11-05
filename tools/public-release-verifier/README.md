# Public release verifier

The Windows x64 verifier uses sigstore-go 1.2.2. It accepts a GitHub release
bundle and a GitHub-only trusted root from the local GitHub CLI's TUF
verification. It requires GitHub's exact release signer identity and a signed
RFC 3161 timestamp. It returns a statement only after cryptographic verification.
The PowerShell updater then checks the signed repository, tag, commit and all
asset names and hashes. Each asset also needs Actions provenance for the exact
release tag and commit.

To reproduce the packaged verifier from this directory with Go 1.26.10:

```powershell
$env:GOTOOLCHAIN = 'local'
$env:CGO_ENABLED = '0'
$env:GOOS = 'windows'
$env:GOARCH = 'amd64'
$env:GOAMD64 = 'v1'
go mod verify
go build -mod=readonly -trimpath -buildvcs=false -ldflags '-s -w' -o release-verifier.exe .
Get-FileHash -Algorithm SHA256 release-verifier.exe
```

Compare the result to the binary in `control-skills/sync-base/runtime` and
its digest in `sync-policy.json`. The adjacent notices cover Go and the modules
linked by the build. Go is a maintainer build tool.
