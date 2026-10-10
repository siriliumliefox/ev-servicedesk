// Пустые состояния, ошибки и загрузка (глава 7): единый вид для всех экранов.
import 'package:flutter/material.dart';

import '../data/repository.dart';
import '../theme/app_theme.dart';

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, this.message, this.action});

  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final content = Padding(
      padding: const EdgeInsets.all(EvSpace.s6),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: EvSpace.s12, color: c.fgMuted),
          const SizedBox(height: EvSpace.s4),
          Text(title, style: Theme.of(context).textTheme.titleMedium, textAlign: TextAlign.center),
          if (message != null) ...[
            const SizedBox(height: EvSpace.s2),
            Text(
              message!,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: c.fgMuted),
              textAlign: TextAlign.center,
            ),
          ],
          if (action != null) ...[const SizedBox(height: EvSpace.s6), action!],
        ],
      ),
    );
    // Внутри списка (неограниченная высота) — как есть; на весь экран — по центру с прокруткой.
    return LayoutBuilder(
      builder: (context, box) => box.hasBoundedHeight ? Center(child: SingleChildScrollView(child: content)) : content,
    );
  }
}

/// Ошибка загрузки; для OfflineException — «Нет подключения к интернету».
class ErrorState extends StatelessWidget {
  const ErrorState({super.key, required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final offline = error is OfflineException;
    return EmptyState(
      icon: offline ? Icons.wifi_off : Icons.error_outline,
      title: offline ? 'Нет подключения к интернету' : 'Не удалось загрузить данные',
      message: offline ? 'Проверьте мобильный интернет или Wi-Fi и повторите' : error.toString(),
      action: FilledButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: const Text('Повторить')),
    );
  }
}

/// Загрузка данных: индикатор → ошибка с «Повторить» → пустое состояние → контент.
class AsyncView<T> extends StatefulWidget {
  const AsyncView({
    super.key,
    required this.load,
    required this.builder,
    this.isEmpty,
    this.empty,
    this.reloadKey,
  });

  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;
  final bool Function(T data)? isEmpty;
  final Widget? empty;

  /// При изменении значения данные загружаются заново.
  final Object? reloadKey;

  @override
  State<AsyncView<T>> createState() => _AsyncViewState<T>();
}

class _AsyncViewState<T> extends State<AsyncView<T>> {
  T? _data;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void didUpdateWidget(covariant AsyncView<T> old) {
    super.didUpdateWidget(old);
    if (old.reloadKey != widget.reloadKey) _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await widget.load();
      if (!mounted) return;
      setState(() {
        _data = data;
        _loading = false;
      });
    } on Exception catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _data == null) return const Center(child: CircularProgressIndicator());
    if (_error != null) return ErrorState(error: _error!, onRetry: _reload);
    final data = _data as T;
    if (widget.isEmpty?.call(data) ?? false) return widget.empty ?? const SizedBox.shrink();
    return widget.builder(context, data, _reload);
  }
}

/// Ошибка у поля без InputDecoration (галочка, группа чипов): под полем, цветом danger-text (глава 9).
/// Живая область (liveRegion) — VoiceOver на iOS и macOS зачитывает ошибку, когда она появляется;
/// SemanticsRole.alert эмбеддеры iOS/macOS не используют. Связь с полем — подсказкой (hint) у самого поля.
class FieldError extends StatelessWidget {
  const FieldError(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      liveRegion: true,
      child: Padding(
        padding: const EdgeInsets.only(top: EvSpace.s1),
        child: Text(message, style: EvTypeMobile.caption.copyWith(color: context.evColors.dangerText)),
      ),
    );
  }
}

/// Сообщение об ошибке действия (отправка формы и т.п.).
void showErrorSnack(BuildContext context, Object error) {
  final text = error is OfflineException ? 'Нет подключения к интернету. Попробуйте позже' : error.toString();
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));
}

/// Индикатор в кнопке на время запроса.
class ButtonProgress extends StatelessWidget {
  const ButtonProgress({super.key});

  @override
  Widget build(BuildContext context) =>
      const SizedBox.square(dimension: EvSize.iconMd, child: CircularProgressIndicator(strokeWidth: 2));
}
