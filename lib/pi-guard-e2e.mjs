// Wrapper del guard de pi para el rol e2e. Ver lib/pi-guard.mjs
import { guard } from "./pi-guard.mjs";

export default function (pi) {
  guard(pi, "e2e");
}
