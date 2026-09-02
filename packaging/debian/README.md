# Debian package preparation

Run on Ubuntu 24.04 or a compatible Debian-based build host:

```bash
chmod +x packaging/debian/build_deb.sh
./packaging/debian/build_deb.sh
```

The build downloads dependencies once and embeds their wheels in the package.
Installation is therefore offline and does not contact PyPI:

```bash
sudo apt install ./dist/mdir-u_2.23.15_amd64.deb
u
```

Before publishing, test install, upgrade, removal, desktop launch, previews,
and `lintian` on a clean Ubuntu 24.04 virtual machine. The `.deb` can then be
attached to the matching GitHub Release. A signed APT repository is a later,
separate distribution step.
