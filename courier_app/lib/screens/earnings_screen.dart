import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api_client.dart';
import '../models.dart';

class EarningsScreen extends StatefulWidget {
  const EarningsScreen({super.key});

  @override
  State<EarningsScreen> createState() => _EarningsScreenState();
}

class _EarningsScreenState extends State<EarningsScreen> {
  final _api = ApiClient();
  late DateTime _month;
  late Future<CourierEarnings> _future;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _month = DateTime(now.year, now.month);
    _future = _api.earnings(month: _month);
  }

  void _changeMonth(int delta) {
    setState(() {
      _month = DateTime(_month.year, _month.month + delta);
      _future = _api.earnings(month: _month);
    });
  }

  Future<void> _refresh() async {
    final next = _api.earnings(month: _month);
    setState(() => _future = next);
    await next;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My Earnings')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(icon: const Icon(Icons.chevron_left), onPressed: () => _changeMonth(-1)),
                Text(DateFormat('MMMM yyyy').format(_month), style: Theme.of(context).textTheme.titleMedium),
                IconButton(icon: const Icon(Icons.chevron_right), onPressed: () => _changeMonth(1)),
              ],
            ),
            const SizedBox(height: 8),
            FutureBuilder<CourierEarnings>(
              future: _future,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.waiting) {
                  return const Padding(
                    padding: EdgeInsets.symmetric(vertical: 60),
                    child: Center(child: CircularProgressIndicator()),
                  );
                }
                if (snapshot.hasError) {
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 40),
                    child: Column(
                      children: [
                        Text('${snapshot.error}'),
                        const SizedBox(height: 12),
                        FilledButton(onPressed: _refresh, child: const Text('Retry')),
                      ],
                    ),
                  );
                }
                final e = snapshot.data!;
                return Column(
                  children: [
                    Card(
                      color: Theme.of(context).colorScheme.primaryContainer,
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Column(
                          children: [
                            const Text('Outstanding'),
                            const SizedBox(height: 4),
                            Text(
                              '\$${e.outstandingDollars.toStringAsFixed(2)}',
                              style: Theme.of(context).textTheme.headlineMedium,
                            ),
                            const SizedBox(height: 4),
                            const Text('Total the platform still owes you', style: TextStyle(fontSize: 12)),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: _StatTile(
                            label: 'Available',
                            value: '\$${e.availableBalanceDollars.toStringAsFixed(2)}',
                            hint: 'Not yet scheduled',
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: _StatTile(
                            label: 'Pending payout',
                            value: '\$${e.pendingPayoutDollars.toStringAsFixed(2)}',
                            hint: 'Scheduled / processing',
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.local_shipping),
                        title: Text('${e.deliveredCount} deliveries this month'),
                        subtitle: Text('Earned \$${e.deliveredTotalDollars.toStringAsFixed(2)}'),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: _StatTile(
                            label: 'Cash on delivery',
                            value: '\$${e.codTotalDollars.toStringAsFixed(2)}',
                            hint: 'Already in your hands',
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: _StatTile(
                            label: 'Bank / card orders',
                            value: '\$${e.bankTotalDollars.toStringAsFixed(2)}',
                            hint: 'Owed by the platform',
                          ),
                        ),
                      ],
                    ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _StatTile extends StatelessWidget {
  final String label;
  final String value;
  final String hint;
  const _StatTile({required this.label, required this.value, required this.hint});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: const TextStyle(color: Colors.grey, fontSize: 12)),
            const SizedBox(height: 4),
            Text(value, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 2),
            Text(hint, style: const TextStyle(fontSize: 11, color: Colors.grey)),
          ],
        ),
      ),
    );
  }
}
