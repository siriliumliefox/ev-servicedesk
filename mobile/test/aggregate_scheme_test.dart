// Схема агрегатов (замечания владельца к главе 18): зоны расположены симметрично, у электромобиля нет агрегатов ДВС.
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/screens/car/aggregate_scheme.dart';

const _iceAggregates = {'engine_oil', 'oil_filter', 'air_filter'};

void main() {
  test('зоны в одном ряду — зеркальная пара или одна по оси авто', () {
    final rows = <double, List<double>>{};
    for (final p in aggregateSchemePositions.values) {
      (rows[p.dy] ??= []).add(p.dx);
    }
    for (final MapEntry(key: y, value: xs) in rows.entries) {
      if (xs.length == 1) {
        expect(xs.single, 0.5, reason: 'ряд $y');
      } else {
        expect(xs, hasLength(2), reason: 'ряд $y');
        expect(xs[0] + xs[1], closeTo(1, 1e-9), reason: 'ряд $y — зеркально относительно оси авто');
      }
    }
  });

  test('агрегаты ДВС — свой ряд или пара: без них (электромобиль) остальные ряды остаются симметричными', () {
    final iceRows = {for (final code in _iceAggregates) aggregateSchemePositions[code]!.dy};
    final otherRows = {
      for (final e in aggregateSchemePositions.entries)
        if (!_iceAggregates.contains(e.key)) e.value.dy,
    };
    expect(iceRows.intersection(otherRows), isEmpty);
  });

  test('электромобиль Zeekr 001: новое авто — без масла двигателя и фильтров ДВС, редуктор есть', () async {
    final repo = PrototypeRepository(latency: Duration.zero);
    final zeekr = await repo.addVehicle('L6TZZZ1Z2RA000001');
    expect(zeekr.vehicleModel.title, 'Zeekr 001');
    final codes = (await repo.aggregateStatuses(zeekr.id)).map((s) => s.aggregateTypeCode).toSet();
    expect(codes.intersection(_iceAggregates), isEmpty);
    expect(codes, contains('gearbox_oil'));
  });
}
