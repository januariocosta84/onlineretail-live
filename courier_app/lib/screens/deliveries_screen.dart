import 'dart:async';

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../maps_launcher.dart';
import '../models.dart';
import '../push_notifications.dart';
import 'availability_screen.dart';
import 'delivery_detail_screen.dart';
import 'earnings_screen.dart';
import 'login_screen.dart';

class DeliveriesScreen extends StatefulWidget {
  const DeliveriesScreen({super.key});

  @override
  State<DeliveriesScreen> createState() => _DeliveriesScreenState();
}

class _DeliveriesScreenState extends State<DeliveriesScreen> with SingleTickerProviderStateMixin {
  final _api = ApiClient();
  late final TabController _tabController;
  late Future<({List<DeliveryOrder> pending, List<DeliveryOrder> delivered})> _future;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _future = _api.deliveries();
    // Covers app-restart-while-already-logged-in — login_screen.dart
    // handles the fresh-login case. init() is idempotent (no-ops if
    // already run this app session).
    unawaited(PushNotifications.init(_api));
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    final next = _api.deliveries();
    setState(() => _future = next);
    await next;
  }

  Future<void> _logout() async {
    await _api.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('My Deliveries'),
        bottom: TabBar(controller: _tabController, tabs: const [
          Tab(text: 'Pending'),
          Tab(text: 'Delivered'),
        ]),
        actions: [
          IconButton(
            icon: const Icon(Icons.payments_outlined),
            tooltip: 'My Earnings',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const EarningsScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.schedule),
            tooltip: 'My Availability',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AvailabilityScreen()),
            ),
          ),
          IconButton(icon: const Icon(Icons.logout), tooltip: 'Log out', onPressed: _logout),
        ],
      ),
      body: FutureBuilder<({List<DeliveryOrder> pending, List<DeliveryOrder> delivered})>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return _ErrorView(error: snapshot.error, onRetry: _refresh);
          }
          final data = snapshot.data!;
          return TabBarView(
            controller: _tabController,
            children: [
              _DeliveryList(orders: data.pending, onRefresh: _refresh, showMarkDelivered: true),
              _DeliveryList(orders: data.delivered, onRefresh: _refresh, showMarkDelivered: false),
            ],
          );
        },
      ),
    );
  }
}

class _DeliveryList extends StatelessWidget {
  final List<DeliveryOrder> orders;
  final Future<void> Function() onRefresh;
  final bool showMarkDelivered;

  const _DeliveryList({required this.orders, required this.onRefresh, required this.showMarkDelivered});

  @override
  Widget build(BuildContext context) {
    if (orders.isEmpty) {
      return RefreshIndicator(
        onRefresh: onRefresh,
        child: ListView(
          children: const [
            SizedBox(height: 120),
            Center(child: Text('Nothing here right now.')),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.separated(
        padding: const EdgeInsets.all(12),
        itemCount: orders.length,
        separatorBuilder: (_, _) => const SizedBox(height: 8),
        itemBuilder: (context, index) {
          final order = orders[index];
          return Card(
            child: ListTile(
              title: Text('${order.orderNumber} — ${order.productName}'),
              subtitle: Text('${order.buyerName}\n${order.deliveryAddress}'),
              isThreeLine: true,
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (order.hasPin)
                    IconButton(
                      icon: const Icon(Icons.pin_drop, color: Colors.redAccent),
                      tooltip: 'Route to buyer',
                      onPressed: () => _openRoute(context, order),
                    ),
                  showMarkDelivered
                      ? const Icon(Icons.chevron_right)
                      : const Icon(Icons.check_circle, color: Colors.green),
                ],
              ),
              onTap: showMarkDelivered
                  ? () async {
                      final delivered = await Navigator.of(context).push<bool>(
                        MaterialPageRoute(builder: (_) => DeliveryDetailScreen(order: order)),
                      );
                      if (delivered == true) onRefresh();
                    }
                  : null,
            ),
          );
        },
      ),
    );
  }
}

Future<void> _openRoute(BuildContext context, DeliveryOrder order) async {
  try {
    await launchRouteTo(order.deliveryLatitude!, order.deliveryLongitude!);
  } catch (_) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open a maps app.')),
      );
    }
  }
}

class _ErrorView extends StatelessWidget {
  final Object? error;
  final Future<void> Function() onRetry;
  const _ErrorView({required this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('$error'),
          const SizedBox(height: 12),
          FilledButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
