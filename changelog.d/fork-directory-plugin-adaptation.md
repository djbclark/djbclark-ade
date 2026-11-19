### Changed
- Extract ordinary claim and naming callback factories and add finite asynchronous SDK business callbacks with lazy synchronous registration tests; native selected-profile wiring remains held pending its committed isolation boundary. (#796)
- Preserve original selected SDK/proof rejection identity when cancellation races it, while retaining ordinary aborted-skip behavior. (#796)
