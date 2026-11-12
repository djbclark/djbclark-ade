### Added
- Added `review-launch --mode trusted` (YOLO: `bypassPermissions` with Bash, no read-boundary claim, needs `--trusted-author` and `--head`) and `review-pr --runtime auto|restricted|yolo`, so a PR the repository owner authored is reviewed by default in the trusted runtime while every other author, `--allow-untrusted` and `--runtime restricted` keep the restricted review boundary. (#574)
### Changed
- Documented the trusted-review runtime split in the review boundary, review rule 11 and the ordinary-agent mode notes. (#574)
