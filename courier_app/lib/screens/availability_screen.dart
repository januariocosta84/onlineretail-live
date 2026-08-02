import 'package:flutter/material.dart';

import '../api_client.dart';
import '../models.dart';

class AvailabilityScreen extends StatefulWidget {
  const AvailabilityScreen({super.key});

  @override
  State<AvailabilityScreen> createState() => _AvailabilityScreenState();
}

class _AvailabilityScreenState extends State<AvailabilityScreen> {
  final _api = ApiClient();
  late Future<List<AvailabilityWindow>> _future;

  @override
  void initState() {
    super.initState();
    _future = _api.listAvailability();
  }

  void _refresh() => setState(() => _future = _api.listAvailability());

  Future<void> _openForm({AvailabilityWindow? existing}) async {
    final saved = await showDialog<bool>(
      context: context,
      builder: (_) => _AvailabilityFormDialog(api: _api, existing: existing),
    );
    if (saved == true) _refresh();
  }

  Future<void> _delete(AvailabilityWindow window) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove this window?'),
        content: Text('${window.weekdayName} ${window.startTime}–${window.endTime}'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Remove')),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _api.deleteAvailability(window.id);
      _refresh();
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My Availability')),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _openForm(),
        child: const Icon(Icons.add),
      ),
      body: FutureBuilder<List<AvailabilityWindow>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          final windows = snapshot.data!;
          if (windows.isEmpty) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: Text(
                  'No schedule set — you\'ll be shown as available at all times until you add one.',
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          return ListView.builder(
            padding: const EdgeInsets.all(12),
            itemCount: windows.length,
            itemBuilder: (context, index) {
              final w = windows[index];
              return Card(
                child: ListTile(
                  title: Text(w.weekdayName),
                  subtitle: Text('${w.startTime} – ${w.endTime}'),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(icon: const Icon(Icons.edit), onPressed: () => _openForm(existing: w)),
                      IconButton(icon: const Icon(Icons.delete_outline), onPressed: () => _delete(w)),
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class _AvailabilityFormDialog extends StatefulWidget {
  final ApiClient api;
  final AvailabilityWindow? existing;
  const _AvailabilityFormDialog({required this.api, this.existing});

  @override
  State<_AvailabilityFormDialog> createState() => _AvailabilityFormDialogState();
}

class _AvailabilityFormDialogState extends State<_AvailabilityFormDialog> {
  late int _weekday;
  TimeOfDay? _start;
  TimeOfDay? _end;
  bool _submitting = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final existing = widget.existing;
    _weekday = existing?.weekday ?? 0;
    _start = existing != null ? _parseTime(existing.startTime) : null;
    _end = existing != null ? _parseTime(existing.endTime) : null;
  }

  TimeOfDay _parseTime(String hhmm) {
    final parts = hhmm.split(':');
    return TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1]));
  }

  String _formatTime(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  Future<void> _pickTime({required bool isStart}) async {
    final picked = await showTimePicker(
      context: context,
      initialTime: (isStart ? _start : _end) ?? const TimeOfDay(hour: 8, minute: 0),
    );
    if (picked == null) return;
    setState(() {
      if (isStart) {
        _start = picked;
      } else {
        _end = picked;
      }
    });
  }

  Future<void> _submit() async {
    if (_start == null || _end == null) {
      setState(() => _error = 'Pick both a start and end time.');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final startStr = _formatTime(_start!);
      final endStr = _formatTime(_end!);
      if (widget.existing == null) {
        await widget.api.createAvailability(weekday: _weekday, startTime: startStr, endTime: endStr);
      } else {
        await widget.api.updateAvailability(widget.existing!.id, weekday: _weekday, startTime: startStr, endTime: endStr);
      }
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.existing == null ? 'Add a working-hours window' : 'Edit window'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DropdownButtonFormField<int>(
            initialValue: _weekday,
            decoration: const InputDecoration(labelText: 'Day'),
            items: [
              for (var i = 0; i < AvailabilityWindow.weekdayNames.length; i++)
                DropdownMenuItem(value: i, child: Text(AvailabilityWindow.weekdayNames[i])),
            ],
            onChanged: (v) => setState(() => _weekday = v!),
          ),
          const SizedBox(height: 12),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(_start == null ? 'Start time' : 'Start: ${_formatTime(_start!)}'),
            trailing: const Icon(Icons.access_time),
            onTap: () => _pickTime(isStart: true),
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(_end == null ? 'End time' : 'End: ${_formatTime(_end!)}'),
            trailing: const Icon(Icons.access_time),
            onTap: () => _pickTime(isStart: false),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: _submitting
              ? const SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Save'),
        ),
      ],
    );
  }
}
