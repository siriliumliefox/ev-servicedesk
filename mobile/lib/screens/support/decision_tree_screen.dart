// Дерево решений по типовой ошибке (GET /knowledge-articles/{id}/decision-tree):
// шаги самопомощи → «решено» или эскалация в тикет с подставленной категорией и ходом диагностики.
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/states.dart';
import 'ticket_create_screen.dart';

class DecisionTreeScreen extends StatelessWidget {
  const DecisionTreeScreen({super.key, required this.article});

  final KnowledgeArticle article;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(article.title)),
      body: AsyncView<List<DecisionTreeNode>>(
        load: () => app.repository.decisionTree(article.id),
        isEmpty: (nodes) => nodes.isEmpty,
        empty: const EmptyState(icon: Icons.build_outlined, title: 'Сценарий пока не заполнен'),
        builder: (context, nodes, _) => _Walker(article: article, nodes: nodes),
      ),
    );
  }
}

class _Walker extends StatefulWidget {
  const _Walker({required this.article, required this.nodes});

  final KnowledgeArticle article;
  final List<DecisionTreeNode> nodes;

  @override
  State<_Walker> createState() => _WalkerState();
}

class _WalkerState extends State<_Walker> {
  /// Пройденные узлы и выбранные ответы — для «Назад» и описания тикета.
  late final List<DecisionTreeNode> _path = [widget.nodes.firstWhere((n) => n.isRoot)];
  final List<String> _answers = [];

  DecisionTreeNode get _node => _path.last;

  void _choose(DecisionTreeOption o) {
    final next = widget.nodes.firstWhere((n) => n.id == o.nextNodeId);
    setState(() {
      _answers.add(o.label);
      _path.add(next);
    });
  }

  void _back() => setState(() {
        _path.removeLast();
        _answers.removeLast();
      });

  String _ticketDescription() {
    final steps = [
      for (var i = 0; i < _answers.length; i++) '— ${_path[i].questionText} → ${_answers[i]}',
    ];
    return '${widget.article.title}. Что уже пробовал(а):\n${steps.join('\n')}';
  }

  void _escalate() {
    final vehicle = AppScope.read(context).vehicle;
    if (vehicle == null) {
      showErrorSnack(context, 'Добавьте авто, чтобы создать обращение');
      return;
    }
    Navigator.of(context).pushReplacement(MaterialPageRoute<void>(
      builder: (_) => TicketCreateScreen(
        vehicleId: vehicle.id,
        category: widget.article.category,
        description: _ticketDescription(),
        sourceArticleId: widget.article.id,
        sourceNodeId: _node.id,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final node = _node;
    return ListView(
      padding: const EdgeInsets.all(EvSpace.s4),
      children: [
        Text('Шаг ${_path.length}', style: text.bodyMedium?.copyWith(color: c.fgMuted)),
        const SizedBox(height: EvSpace.s2),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(EvSpace.s4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  node.isResolved
                      ? Icons.check_circle_outline
                      : node.isEscalation
                          ? Icons.support_agent
                          : Icons.help_outline,
                  color: node.isResolved ? c.statusGreenFg : c.primaryText,
                ),
                const SizedBox(width: EvSpace.s3),
                Expanded(child: Text(node.questionText, style: text.bodyLarge)),
              ],
            ),
          ),
        ),
        const SizedBox(height: EvSpace.s4),
        for (final o in node.options) ...[
          OutlinedButton(
              // Новый узел — новые кнопки: без «залипшей» подсветки нажатой кнопки прошлого шага.
              key: ValueKey('${node.id}:${o.label}'),
              onPressed: () => _choose(o),
              child: Text(o.label, textAlign: TextAlign.center)),
          const SizedBox(height: EvSpace.s3),
        ],
        if (node.isEscalation)
          FilledButton.icon(
            key: const Key('escalate'),
            onPressed: _escalate,
            icon: const Icon(Icons.add_comment_outlined),
            label: const Text('Создать обращение'),
          ),
        if (node.isResolved) FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Готово')),
        if (_path.length > 1) ...[
          const SizedBox(height: EvSpace.s3),
          TextButton.icon(onPressed: _back, icon: const Icon(Icons.undo), label: const Text('Предыдущий шаг')),
        ],
      ],
    );
  }
}
