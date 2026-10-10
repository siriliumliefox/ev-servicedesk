import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/main.dart';

void main() {
  testWidgets('Приложение запускается с онбординга', (tester) async {
    await tester.pumpWidget(EvServiceDeskApp(repository: PrototypeRepository(latency: Duration.zero)));
    expect(find.text('Цифровой паспорт автомобиля'), findsOneWidget);
    expect(find.text('Получить код'), findsOneWidget);
  });
}
