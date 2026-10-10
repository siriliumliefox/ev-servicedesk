// «Обучение»: инструкции для модели выбранного авто (GET /knowledge-articles?article_type=guide).
// Правило 3-х кликов: обучающий материал — 2 тапа («Обучение» → статья); для другого авто аккаунта — 4
// («Обучение» → переключатель → авто → статья): переключатель тот же, что на «Авто» (U-06, глава 9).
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/demo_panel.dart';
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
        actions: const [DemoButton()],
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
    final preview = article.content.split('\n').first;
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

class ArticleScreen extends StatelessWidget {
  const ArticleScreen({super.key, required this.article});

  final KnowledgeArticle article;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(EvSpace.s4, 0, EvSpace.s4, EvSpace.s8),
          children: [
            Text(article.title, style: text.headlineMedium),
            const SizedBox(height: EvSpace.s4),
            for (final p in article.content.split('\n\n')) ...[
              Text(p, style: text.bodyLarge),
              const SizedBox(height: EvSpace.s4),
            ],
          ],
        ),
      ),
    );
  }
}
