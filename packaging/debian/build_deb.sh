#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$ROOT/mdir_u/__init__.py")
ARCH=$(dpkg --print-architecture)
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM
PKG="$STAGE/mdir-u_${VERSION}_${ARCH}"
OUT="$ROOT/dist/mdir-u_${VERSION}_${ARCH}.deb"

mkdir -p "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/share/applications" \
    "$PKG/usr/share/icons/hicolor/256x256/apps" "$PKG/usr/share/mdir-u/wheels" \
    "$ROOT/dist"

python3 -m pip wheel "$ROOT[preview]" --wheel-dir "$PKG/usr/share/mdir-u/wheels"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@ARCH@/$ARCH/g" \
    "$ROOT/packaging/debian/control.in" > "$PKG/DEBIAN/control"
sed "s/@VERSION@/$VERSION/g" "$ROOT/packaging/debian/postinst" > "$PKG/DEBIAN/postinst"
install -m 755 "$ROOT/packaging/debian/prerm" "$PKG/DEBIAN/prerm"
install -m 755 "$ROOT/packaging/debian/u" "$PKG/usr/bin/u"
ln -s u "$PKG/usr/bin/mdir-u"
install -m 644 "$ROOT/packaging/debian/mdir-u.desktop" "$PKG/usr/share/applications/mdir-u.desktop"
install -m 644 "$ROOT/mdir_u/assets/mdir.png" "$PKG/usr/share/icons/hicolor/256x256/apps/mdir-u.png"
install -m 644 "$ROOT/LICENSE" "$PKG/usr/share/mdir-u/LICENSE"
chmod 755 "$PKG/DEBIAN/postinst"
dpkg-deb --root-owner-group --build "$PKG" "$OUT"
(cd "$ROOT/dist" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256")
printf '%s\n' "Built $OUT"
