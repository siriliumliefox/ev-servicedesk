import 'package:flutter/material.dart';

// Каркас, Глава 4. Реальный флоу онбординга/авторизации — Глава 18.
void main() {
  runApp(const EvServiceDeskApp());
}

class EvServiceDeskApp extends StatelessWidget {
  const EvServiceDeskApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'EV-ServiceDesk',
      home: Scaffold(
        appBar: AppBar(title: const Text('EV-ServiceDesk')),
        body: const Center(
          child: Text('Каркас мобильного приложения — Глава 4'),
        ),
      ),
    );
  }
}
