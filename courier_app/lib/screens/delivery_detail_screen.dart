import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api_client.dart';
import '../maps_launcher.dart';
import '../models.dart';
import '../whatsapp_launcher.dart';

class DeliveryDetailScreen extends StatefulWidget {
  final DeliveryOrder order;
  const DeliveryDetailScreen({super.key, required this.order});

  @override
  State<DeliveryDetailScreen> createState() => _DeliveryDetailScreenState();
}

class _DeliveryDetailScreenState extends State<DeliveryDetailScreen> with WidgetsBindingObserver {
  final _api = ApiClient();
  final _picker = ImagePicker();

  late DeliveryOrder _order;
  Timer? _pollTimer;

  File? _photo;
  bool _submitting = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _order = widget.order;
    WidgetsBinding.instance.addObserver(this);
    _startPolling();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pollTimer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // The seller confirming pickup (or a courier rejecting elsewhere,
    // etc.) happens outside this screen entirely — nothing here pushes an
    // update, so it has to notice on its own. Same reasoning as the
    // Pending list's own poll.
    if (state == AppLifecycleState.resumed) {
      unawaited(_refreshOrder());
      _startPolling();
    } else if (state == AppLifecycleState.paused) {
      _pollTimer?.cancel();
    }
  }

  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 10), (_) => _refreshOrder());
  }

  Future<void> _refreshOrder() async {
    try {
      final data = await _api.deliveries();
      final matches = [...data.pending, ...data.delivered].where((o) => o.id == _order.id);
      if (matches.isNotEmpty && mounted) setState(() => _order = matches.first);
    } catch (_) {
      // Best-effort — the next tick just tries again, same as the list's poll.
    }
  }

  Future<void> _pickPhoto(ImageSource source) async {
    final picked = await _picker.pickImage(source: source, maxWidth: 1600, imageQuality: 85);
    if (picked != null) setState(() => _photo = File(picked.path));
  }

  Future<void> _showPhotoSourceSheet() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (context) => SafeArea(
        child: Wrap(children: [
          ListTile(
            leading: const Icon(Icons.photo_camera),
            title: const Text('Take a photo'),
            onTap: () => Navigator.of(context).pop(ImageSource.camera),
          ),
          ListTile(
            leading: const Icon(Icons.photo_library),
            title: const Text('Choose from gallery'),
            onTap: () => Navigator.of(context).pop(ImageSource.gallery),
          ),
        ]),
      ),
    );
    if (source != null) await _pickPhoto(source);
  }

  Future<void> _submit() async {
    if (_photo == null) {
      setState(() => _error = 'A delivery photo is required.');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await _api.markDelivered(_order.id, _photo!);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Order marked as delivered.')),
      );
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Could not reach the server — check your connection.');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final order = _order;
    return Scaffold(
      appBar: AppBar(title: Text(order.orderNumber)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _DetailRow(label: 'Product', value: order.productName),
          const SizedBox(height: 16),
          Text('Pickup', style: Theme.of(context).textTheme.titleMedium),
          _DetailRow(label: 'From', value: order.sellerName),
          _DetailRow(label: 'Address', value: order.sellerAddress),
          if (order.sellerHasPin) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () => _openRoute(context, order.sellerLatitude!, order.sellerLongitude!),
              icon: const Icon(Icons.directions),
              label: const Text('Route to pickup'),
            ),
          ],
          const SizedBox(height: 16),
          Text('Deliver to', style: Theme.of(context).textTheme.titleMedium),
          _DetailRow(label: 'Buyer', value: order.buyerName),
          _DetailRow(label: 'Address', value: order.deliveryAddress),
          _DetailRow(
            label: 'Phone',
            value: order.deliveryPhone,
            onTap: () => _openWhatsApp(context, order.deliveryPhone),
            trailing: const Icon(Icons.chat, size: 18, color: Colors.green),
          ),
          // Cash on delivery is the only method where the courier actually
          // collects money from the buyer — for every electronic method
          // (card, bank transfer) the platform already has it, so showing
          // an amount here would just invite confusion about what's owed.
          // Broken into product price + delivery fee (see
          // settings.DELIVERY_FEE) so it reads like a receipt instead of
          // leaving the courier to work out why the total doesn't match
          // the product price alone.
          if (order.isCashOnDelivery) ...[
            _DetailRow(label: 'Collect (cash)', value: '\$${order.subtotal}'),
            _DetailRow(label: 'Delivery fee', value: '\$${order.deliveryFee}'),
            _DetailRow(label: 'Total collect (cash)', value: '\$${order.total}'),
          ],
          if (order.hasPin) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () => _openRoute(context, order.deliveryLatitude!, order.deliveryLongitude!),
              icon: const Icon(Icons.directions),
              label: const Text('Route to buyer'),
            ),
          ],
          if (order.awaitingSellerPickupConfirm) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  const Icon(Icons.hourglass_top, size: 20),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: Text(
                      "Waiting for the seller to confirm they've handed this over to you — "
                      "you'll be able to mark it delivered once they do.",
                    ),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 24),
          Text('Delivery photo', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          if (_photo != null)
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Image.file(_photo!, height: 220, fit: BoxFit.cover),
            ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _showPhotoSourceSheet,
            icon: const Icon(Icons.camera_alt),
            label: Text(_photo == null ? 'Add photo' : 'Retake photo'),
          ),
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 24),
          FilledButton(
            onPressed: (_submitting || order.awaitingSellerPickupConfirm) ? null : _submit,
            child: _submitting
                ? const SizedBox(
                    height: 20, width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Text('Mark Delivered'),
          ),
        ],
      ),
    );
  }
}

Future<void> _openRoute(BuildContext context, double lat, double lng) async {
  try {
    await launchRouteTo(lat, lng);
  } catch (_) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open a maps app.')),
      );
    }
  }
}

Future<void> _openWhatsApp(BuildContext context, String phone) async {
  try {
    await launchWhatsApp(phone);
  } catch (_) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open WhatsApp.')),
      );
    }
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;
  final VoidCallback? onTap;
  final Widget? trailing;
  const _DetailRow({required this.label, required this.value, this.onTap, this.trailing});

  @override
  Widget build(BuildContext context) {
    final row = Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 90, child: Text(label, style: const TextStyle(color: Colors.grey))),
          Expanded(child: Text(value)),
          ?trailing,
        ],
      ),
    );
    if (onTap == null) return row;
    return InkWell(onTap: onTap, child: row);
  }
}
