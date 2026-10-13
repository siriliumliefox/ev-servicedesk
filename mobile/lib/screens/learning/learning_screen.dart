// «Обучение»: инструкции для модели выбранного авто (GET /knowledge-articles?article_type=guide).
// Правило 3-х кликов: обучающий материал — 2 тапа («Обучение» → статья); для другого авто аккаунта — 4
// («Обучение» → переключатель → авто → статья): переключатель тот же, что на «Авто» (U-06, глава 9).
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/demo_panel.dart';
import '../../ui/notification_bell.dart';
import '../../ui/states.dart';
import '../car/vehicle_switcher.dart';

class LearningScreen extends StatelessWidget {
  const LearningScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final vehicle = app.vehicle;
    // Несколько авто — статьи выбранного, сменить можно здесь же; одно авто — модель в заголовке.
    final switchable = vehicle != null && app.vehicles.length > 1;
    return Scaffold(
      appBar: AppBar(
        title: Text(vehicle == null || switchable ? 'Обучение' : 'Обучение · ${vehicle.vehicleModel.title}'),
        actions: const [NotificationBell(), DemoButton()],
        bottom: switchable
            ? PreferredSize(
                preferredSize: const Size.fromHeight(EvSize.controlMobile + EvSpace.s2),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(EvSpace.s2, 0, EvSpace.s2, EvSpace.s2),
                  child: Align(alignment: Alignment.centerLeft, child: VehicleSwitcher(vehicle: vehicle)),
                ),
              )
            : null,
      ),
      body: vehicle == null
          ? const EmptyState(
              icon: Icons.school_outlined,
              title: 'Инструкции появятся после добавления авто',
              message: 'Подберём материалы для вашей модели и версии прошивки',
            )
          : AsyncView<List<KnowledgeArticle>>(
              key: ValueKey(vehicle.vehicleModel.id),
              reloadKey: app.revision,
              load: () => app.repository.articles(vehicle.vehicleModel.id, ArticleType.guide),
              isEmpty: (items) => items.isEmpty,
              empty: const EmptyState(
                icon: Icons.menu_book_outlined,
                title: 'Инструкций для этой модели пока нет',
                message: 'Мы готовим материалы — пришлём уведомление, когда они появятся',
              ),
              builder: (context, items, reload) => RefreshIndicator(
                onRefresh: reload,
                child: ListView.separated(
                  padding: const EdgeInsets.all(EvSpace.s4),
                  itemCount: items.length,
                  separatorBuilder: (_, __) => const SizedBox(height: EvSpace.s3),
                  itemBuilder: (context, i) => ArticleCard(
                    article: items[i],
                    onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                      builder: (_) => ArticleScreen(article: items[i]),
                    )),
                  ),
                ),
              ),
            ),
    );
  }
}

class ArticleCard extends StatelessWidget {
  const ArticleCard({super.key, required this.article, required this.onTap, this.icon = Icons.article_outlined});

  final KnowledgeArticle article;
  final VoidCallback onTap;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final preview = markdownPreview(article.content);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        key: Key('article-${article.id}'),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(EvSpace.s4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: c.primaryText),
              const SizedBox(width: EvSpace.s3),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(article.title, style: text.titleMedium),
                    const SizedBox(height: EvSpace.s1),
                    Text(
                      preview,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: text.bodyMedium?.copyWith(color: c.fgMuted),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: EvSpace.s2),
              Icon(Icons.chevron_right, color: c.fgMuted),
            ],
          ),
        ),
      ),
    );
  }
}

/// Первая содержательная строка статьи без разметки Markdown — для карточки в списке.
String markdownPreview(String markdown) {
  for (final raw in markdown.split('\n')) {
    final line = raw
        .replaceFirst(RegExp(r'^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)'), '')
        .replaceAllMapped(RegExp(r'!?\[([^\]]*)\]\([^)]*\)'), (m) => m[1]!)
        .replaceAll(RegExp(r'[*_`~]'), '')
        .trim();
    if (line.isNotEmpty && !RegExp(r'^[-=|: ]+$').hasMatch(line)) return line;
  }
  return '';
}

/// Текст статьи — CommonMark (ADR 0024 п. 7): картинки в v1 не показываются, ссылки — во внешнем браузере.
class ArticleScreen extends StatelessWidget {
  const ArticleScreen({super.key, required this.article});

  final KnowledgeArticle article;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final text = theme.textTheme;
    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(EvSpace.s4, 0, EvSpace.s4, EvSpace.s8),
          children: [
            Text(article.title, style: text.headlineMedium),
            const SizedBox(height: EvSpace.s4),
            MarkdownBody(
              key: const Key('article-content'),
              data: article.content,
              styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
                p: text.bodyLarge,
                h1: text.titleLarge,
                h2: text.titleLarge,
                h3: text.titleMedium,
                listBullet: text.bodyLarge,
                pPadding: const EdgeInsets.only(bottom: EvSpace.s2),
                blockSpacing: EvSpace.s3,
              ),
              imageBuilder: (_, __, ___) => const SizedBox.shrink(),
              onTapLink: (_, href, __) {
                final uri = href == null ? null : Uri.tryParse(href);
                if (uri != null && (uri.scheme == 'https' || uri.scheme == 'http')) {
                  launchUrl(uri, mode: LaunchMode.externalApplication);
                }
              },
            ),
          ],
        ),
      ),
    );
  }
}
