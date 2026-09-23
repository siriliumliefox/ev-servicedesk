import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/main.dart';

void main() {
  testWidgets('Приложение запускается и показывает заголовок', (tester) async {
    await tester.pumpWidget(const EvServiceDeskApp());
    expect(find.text('EV-ServiceDesk'), findsOneWidget);
  });
}
