# Socks5

A simple and lightweight socks5 server for iOS.

## Features

* IPv4/IPv6. (dual stack)
* Standard `CONNECT` command.
* Standard `UDP ASSOCIATE` command.
* Extended `FWD UDP` command. (UDP in TCP)
* Multiple username/password authentication.

## How to Build

### HevSocks5Server.xcframework

```bash
git clone --recursive https://github.com/heiher/hev-socks5-server
cd hev-socks5-server
./build-apple.sh
```

### Xcode

1. Copy HevSocks5Server.xcframework to this project directory.
2. Build it with Xcode.

## Dependencies

* HevSocks5Server - https://github.com/heiher/hev-socks5-server

## Contributors

* **hev** - https://hev.cc

## License

MIT
