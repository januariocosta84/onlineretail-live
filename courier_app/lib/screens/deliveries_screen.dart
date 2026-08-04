import 'dart:async';

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../auth_storage.dart';
import '../maps_launcher.dart';
import '../models.dart';
import '../push_notifications.dart';
import 'availability_screen.dart';
import 'delivery_detail_screen.dart';
import 'earnings_screen.dart';
import 'login_screen.dart';
import 'profile_screen.dart';

class DeliveriesScreen extends StatefulWidget {
  const DeliveriesScreen({super.key});

  @override
  State<DeliveriesScreen> createState() => _DeliveriesScreenState();
}

class _DeliveriesScreenState extends State<DeliveriesScreen>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  final _api = ApiClient();
  late final TabController _tabController;
  Timer? _pollTimer;

  bool _loading = true;
  bool _hasData = false;
  Object? _error;
  List<DeliveryOrder> _pending = [];
  List<DeliveryOrder> _delivered = [];

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    WidgetsBinding.instance.addObserver(this);
    unawaited(_load(showSpinner: true));
    _startPolling();
    // Covers app-restart-while-already-logged-in — login_screen.dart
    // handles the fresh-login case. init() is idempotent (no-ops if
    // already run this app session).
    unawaited(PushNotifications.init(_api));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pollTimer?.cancel();
    _tabController.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // A courier can be unassigned (seller reassigns, admin steps in, etc.)
    // while this screen is just sitting open or backgrounded — there's no
    // push/websocket telling this screen to update, so it has to notice on
    // its own. Same reasoning the web order_detail page uses for its own
    // status poll: cheap, reliable, no server push infra required. Paused
    // while backgrounded (nothing to show anyone, no point spending
    // battery/data) and always re-synced the instant the app is foreground
    // again, not just on the next tick.
    if (state == AppLifecycleState.resumed) {
      unawaited(_load());
      _startPolling();
    } else if (state == AppLifecycleState.paused) {
      _pollTimer?.cancel();
    }
  }

  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 10), (_) => _load());
  }

  /// [showSpinner] is only used for the very first load — a background
  /// poll swapping the list contents under a full-screen spinner would be
  /// far more jarring than the (rare) case of a stale row lingering for up
  /// to one poll interval.
  Future<void> _load({bool showSpinner = false}) async {
    if (showSpinner) setState(() => _loading = true);
    try {
      final data = await _api.deliveries();
      if (!mounted) return;
      setState(() {
        _pending = data.pending;
        _delivered = data.delivered;
        _error = null;
        _loading = false;
        _hasData = true;
      });
    } catch (e) {
      if (!mounted) return;
      // A background poll (or a resume-triggered refresh) hitting a
      // transient network blip shouldn't blank an already-loaded list —
      // it just quietly retries on the next tick. Only surface the
      // full-page error view when there's nothing on screen yet to fall
      // back to (first load, or every attempt since has also failed).
      setState(() {
        _loading = false;
        if (!_hasData) _error = e;
      });
    }
  }

  Future<void> _refresh() => _load();

  Future<void> _logout() async {
    // Must happen before _api.logout() clears the stored auth token —
    // unregisterDeviceToken needs it to authenticate the request.
    await PushNotifications.unregister(_api);
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
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Image.asset('assets/timormart_mark.png', height: 28),
            const SizedBox(width: 10),
            const Text('My Deliveries'),
          ],
        ),
        bottom: TabBar(controller: _tabController, tabs: const [
          Tab(text: 'Pending'),
          Tab(text: 'Delivered'),
        ]),
      ),
      drawer: _AppDrawer(onLogout: _logout),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return _ErrorView(error: _error, onRetry: _refresh);
    }
    return TabBarView(
      controller: _tabController,
      children: [
        _DeliveryList(orders: _pending, onRefresh: _refresh, showMarkDelivered: true, api: _api),
        _DeliveryList(orders: _delivered, onRefresh: _refresh, showMarkDelivered: false, api: _api),
      ],
    );
  }
}

class _AppDrawer extends StatelessWidget {
  final Future<void> Function() onLogout;
  const _AppDrawer({required this.onLogout});

  void _go(BuildContext context, Widget screen) {
    Navigator.of(context).pop(); // close the drawer first
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
  }

  @override
  Widget build(BuildContext context) {
    return Drawer(
      child: SafeArea(
        child: Column(
          children: [
            DrawerHeader(
              decoration: BoxDecoration(color: Theme.of(context).colorScheme.primary),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 26,
                    backgroundColor: Colors.white,
                    child: Padding(
                      padding: const EdgeInsets.all(6),
                      child: Image.asset('assets/timormart_mark.png'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FutureBuilder<String?>(
                      future: AuthStorage().readCourierName(),
                      builder: (context, snapshot) => Text(
                        snapshot.data ?? 'TimorMart Courier',
                        style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w600),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            ListTile(
              leading: const Icon(Icons.person_outline),
              title: const Text('My Profile'),
              onTap: () => _go(context, const ProfileScreen()),
            ),
            ListTile(
              leading: const Icon(Icons.payments_outlined),
              title: const Text('My Earnings'),
              onTap: () => _go(context, const EarningsScreen()),
            ),
            ListTile(
              leading: const Icon(Icons.schedule),
              title: const Text('My Availability'),
              onTap: () => _go(context, const AvailabilityScreen()),
            ),
            const Spacer(),
            const Divider(height: 1),
            ListTile(
              leading: Icon(Icons.logout, color: Theme.of(context).colorScheme.error),
              title: Text('Log out', style: TextStyle(color: Theme.of(context).colorScheme.error)),
              onTap: () {
                Navigator.of(context).pop();
                onLogout();
              },
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

class _DeliveryList extends StatelessWidget {
  final List<DeliveryOrder> orders;
  final Future<void> Function() onRefresh;
  final bool showMarkDelivered;
  final ApiClient api;

  const _DeliveryList({
    required this.orders,
    required this.onRefresh,
    required this.showMarkDelivered,
    required this.api,
  });

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
          // Nothing to do on the mark-delivered screen until this is
          // accepted and picked up anyway (see _courier_can_mark_delivered's
          // PICKED_UP gate) — show Accept/Reject in place of the usual
          // tap-through row instead.
          if (showMarkDelivered && order.awaitingMyResponse) {
            return _AwaitingResponseCard(order: order, api: api, onRefresh: onRefresh);
          }
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

class _AwaitingResponseCard extends StatefulWidget {
  final DeliveryOrder order;
  final ApiClient api;
  final Future<void> Function() onRefresh;

  const _AwaitingResponseCard({required this.order, required this.api, required this.onRefresh});

  @override
  State<_AwaitingResponseCard> createState() => _AwaitingResponseCardState();
}

class _AwaitingResponseCardState extends State<_AwaitingResponseCard> {
  bool _submitting = false;

  Future<void> _respond(bool accept) async {
    setState(() => _submitting = true);
    try {
      await widget.api.respondToAssignment(widget.order.id, accept: accept);
      // The row disappears from Pending once this order's status changes
      // (rejected orders are excluded server-side, accepted ones just lose
      // their Accept/Reject buttons) — onRefresh() picks that up.
      await widget.onRefresh();
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not reach the server — check your connection.')),
        );
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final order = widget.order;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${order.orderNumber} — ${order.productName}', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            Text('${order.buyerName}\n${order.deliveryAddress}'),
            const SizedBox(height: 10),
            Text(
              'New delivery assigned to you — accept or reject it.',
              style: TextStyle(fontWeight: FontWeight.w600, color: Theme.of(context).colorScheme.primary),
            ),
            const SizedBox(height: 10),
            _submitting
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                    ),
                  )
                : Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: () => _respond(false),
                          icon: const Icon(Icons.close),
                          label: const Text('Reject'),
                          style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: () => _respond(true),
                          icon: const Icon(Icons.check),
                          label: const Text('Accept'),
                        ),
                      ),
                    ],
                  ),
          ],
        ),
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
