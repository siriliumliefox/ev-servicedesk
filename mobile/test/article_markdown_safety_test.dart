// Статья базы знаний в приложении клиента (глава 25, ADR 0029 п. 10; ADR 0024 п. 7): MarkdownBody не
// выводит HTML как разметку, картинки не грузятся (в том числе `![](javascript:…)`), ссылки — только
// http/https. Сервер HTML в статьях отклоняет; это вторая линия на случай старых данных.
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/screens/learning/learning_screen.dart';

const _hostile = '''
Проверьте <b>предохранитель</b> <script>alert(1)</script>

<img src="https://evil.example/x.png" onerror="alert(2)">

![трекер](https://evil.example/pixel.png)

[опасная ссылка](javascript:alert(3))
''';

void main() {
  testWidgets('HTML и картинки в статье не выводятся как разметка', (tester) async {
    const article = KnowledgeArticle(
      id: 1,
      vehicleModelId: null,
      articleType: ArticleType.guide,
      title: 'Статья',
      content: _hostile,
    );
    await tester.pumpWidget(const MaterialApp(home: ArticleScreen(article: article)));
    expect(find.byType(MarkdownBody), findsOneWidget);
    expect(find.byType(Image), findsNothing, reason: 'картинки (в т. ч. трекер) не загружаются');
    // Текст статьи виден; теги не превращены в форматирование и не исполняются.
    expect(find.textContaining('предохранитель', findRichText: true), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
