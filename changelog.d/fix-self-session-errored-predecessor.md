### Changed

- `bin/ade-self-session finish` retires a predecessor in Paseo `error` status (out of quota) at once after the successor's
  acknowledgement, without the stable-idle wait (operator ruling 2026-11-21). (#852)
