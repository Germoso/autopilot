#!/usr/bin/env bash
# ============================================================
#  e2e-setup.sh — instala lo que necesita el agente e2e-tester (una vez, lo corre el humano)
#
#  Todo queda en ~/.local/share/autopilot-e2e (AUTOPILOT_E2E_HOME), sin sudo y sin tocar tu
#  configuracion global (ni tu Flutter, ni tu Java, ni ~/.android):
#    - Java 17 (Temurin)
#    - Android SDK: cmdline-tools, platform-tools (adb), emulador, imagen android-34 x86_64
#      y el AVD "autopilot_e2e" (Pixel 6, 2 GB de RAM)
#    - Playwright + Chromium (pruebas web: BackOffice y apps Flutter compiladas para web)
#  Es idempotente: lo que ya esta, no se vuelve a bajar. Ocupa ~6 GB.
#
#  uso: e2e-setup.sh [--sin-android] [--sin-web]
# ============================================================
set -euo pipefail
H="${AUTOPILOT_E2E_HOME:-$HOME/.local/share/autopilot-e2e}"
SDK="$H/android-sdk"; JDK="$H/jdk"; AVD_HOME="$H/avd"; AVD=autopilot_e2e
IMAGEN="system-images;android-34;google_apis;x86_64"
CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
JDK_URL="https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse"
ANDROID=1; WEB=1
for a in "$@"; do
  case "$a" in
    --sin-android) ANDROID=0 ;;
    --sin-web) WEB=0 ;;
    -h|--help) sed -n 2,15p "$0"; exit 0 ;;
    *) echo "argumento desconocido: $a" >&2; exit 1 ;;
  esac
done
say(){ echo "  ✓ $*"; }
paso(){ echo; echo "==> $*"; }
mkdir -p "$H"

if [[ $ANDROID == 1 ]]; then
  paso "Java 17 en $JDK"
  if [[ -x "$JDK/bin/java" ]]; then say "ya estaba ($("$JDK/bin/java" -version 2>&1 | head -1))"
  else
    tmp="$(mktemp -d)"; curl -fL --progress-bar "$JDK_URL" -o "$tmp/jdk.tgz"
    mkdir -p "$JDK" && tar -xzf "$tmp/jdk.tgz" -C "$JDK" --strip-components=1 && rm -rf "$tmp"
    say "$("$JDK/bin/java" -version 2>&1 | head -1)"
  fi
  export JAVA_HOME="$JDK" ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK" ANDROID_AVD_HOME="$AVD_HOME"
  export PATH="$JDK/bin:$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$SDK/emulator:$PATH"

  paso "Android SDK en $SDK"
  if [[ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]]; then
    tmp="$(mktemp -d)"; curl -fL --progress-bar "$CMDLINE_URL" -o "$tmp/cmd.zip"
    unzip -q "$tmp/cmd.zip" -d "$tmp" && mkdir -p "$SDK/cmdline-tools" && rm -rf "$SDK/cmdline-tools/latest"
    mv "$tmp/cmdline-tools" "$SDK/cmdline-tools/latest" && rm -rf "$tmp"
  fi
  say "cmdline-tools"
  yes 2>/dev/null | sdkmanager --sdk_root="$SDK" --licenses >/dev/null || true
  sdkmanager --sdk_root="$SDK" "platform-tools" "emulator" "platforms;android-35" "build-tools;35.0.0" "$IMAGEN" \
    | grep -v '^\[' || true
  say "platform-tools, emulador, android-35 e imagen android-34"

  paso "AVD $AVD"
  mkdir -p "$AVD_HOME"
  if [[ ! -f "$AVD_HOME/$AVD.ini" ]]; then
    echo no | avdmanager create avd -n "$AVD" -k "$IMAGEN" -d pixel_6 --force >/dev/null
  fi
  cfg="$AVD_HOME/$AVD.avd/config.ini"
  for kv in "hw.ramSize=2048" "hw.keyboard=yes" "disk.dataPartition.size=6G" "hw.gpu.enabled=yes" "hw.gpu.mode=swiftshader_indirect"; do
    k="${kv%%=*}"; grep -q "^$k" "$cfg" && sed -i "s|^$k.*|$kv|" "$cfg" || echo "$kv" >> "$cfg"
  done
  say "$AVD (Pixel 6, 2 GB) en $AVD_HOME"

  paso "KVM (aceleracion del emulador)"
  if [[ -r /dev/kvm && -w /dev/kvm ]]; then say "/dev/kvm accesible"
  else
    echo "  ✗ sin acceso a /dev/kvm: el emulador no arranca (o va lentisimo). Unico paso con sudo:"
    echo "      sudo usermod -aG kvm \$USER   (y cerrar sesion)"
  fi
fi

if [[ $WEB == 1 ]]; then
  paso "Playwright + Chromium en $H/node"
  command -v npm >/dev/null || { echo "  ✗ falta node/npm" >&2; exit 1; }
  mkdir -p "$H/node"
  [[ -f "$H/node/package.json" ]] || echo '{"name":"autopilot-e2e","private":true}' > "$H/node/package.json"
  [[ -d "$H/node/node_modules/@playwright/test" ]] || npm install --prefix "$H/node" --no-audit --no-fund @playwright/test >/dev/null
  node "$H/node/node_modules/@playwright/test/cli.js" install chromium >/dev/null
  say "Playwright $(node "$H/node/node_modules/@playwright/test/cli.js" --version | awk '{print $2}') + Chromium"
fi

echo
python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/e2e.py" doctor
