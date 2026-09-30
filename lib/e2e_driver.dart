// Driver de las pruebas E2E en Android (plantilla del kit). El agente e2e-tester lo copia a
// test_driver/e2e_driver.dart en SU copia E2E (nunca se commitea) y corre:
//   e2e.sh app <copia> -- fvm flutter drive --driver=test_driver/e2e_driver.dart \
//       --target=integration_test/<prueba>_test.dart -d <serial>
// Cada binding.takeScreenshot('<criterio>-android-<nn>-<paso>') de la prueba se guarda como PNG en
// $E2E_CAPTURAS (<copia>/.e2e-capturas/android).
import 'dart:io';

import 'package:integration_test/integration_test_driver_extended.dart';

Future<void> main() async {
  final dir = Platform.environment['E2E_CAPTURAS'] ?? '.e2e-capturas/android';
  await integrationDriver(
    onScreenshot: (String name, List<int> bytes, [Map<String, Object?>? args]) async {
      final f = File('$dir/$name.png');
      f.parent.createSync(recursive: true);
      f.writeAsBytesSync(bytes);
      stdout.writeln('CAPTURA ${f.absolute.path}');
      return true;
    },
  );
}
