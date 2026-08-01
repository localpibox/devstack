#!/usr/bin/env bash
# update.sh — Update extensions and patches in the running container
# Usage: update.sh [--extensions|--patches|--all]
#   --extensions  Update Pi extensions (default)
#   --patches     Apply/un-apply Pi source patches
#   --all         Update extensions and patches

set -euo pipefail

MODE="extensions"
while [ $# -gt 0 ]; do
    case "$1" in
        --extensions) MODE="extensions"; shift ;;
        --patches)    MODE="patches"; shift ;;
        --all)        MODE="all"; shift ;;
        -h|--help)    echo "Usage: $0 [--extensions|--patches|--all]"; exit 0 ;;
        *)            echo "Usage: $0 [--extensions|--patches|--all]" >&2; exit 1 ;;
    esac
done

G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; N='\033[0m'

update_extensions() {
    echo -e "\n${C}${B}=== Extensions ===${N}"
    echo "  pi update --extensions"
    if pi update --extensions 2>&1; then
        echo -e "  ${G}✓ extensions updated${N}"
    else
        echo -e "  ${Y}⚠ some extensions may need attention${N}"
    fi
    echo -e "\n  Installed:"
    pi list 2>/dev/null | sed 's/^/    /'
}

update_patches() {
    echo -e "\n${C}${B}=== Patches ===${N}"
    if [ ! -d "/opt/pi-src/.git" ]; then
        echo -e "  ${Y}⚠ no git source — patches are baked into the image${N}"
        echo "  To re-apply patches, rebuild the container with updated patch files."
        return 0
    fi
    (cd /opt/pi-src && for p in /opt/pi-patches/pi-*.patch; do
        [ -f "$p" ] || continue
        if git am "$p" 2>&1; then
            echo -e "  ${G}✓ $(basename "$p" .patch)${N}"
        else
            echo -e "  ${Y}⚠ $(basename "$p" .patch) — conflict, resolve manually${N}"
        fi
    done)
}

case "$MODE" in
    extensions) update_extensions ;;
    patches)    update_patches ;;
    all)        update_extensions; update_patches ;;
esac

echo -e "\n${G}Done.${N}"
