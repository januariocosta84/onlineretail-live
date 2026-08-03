import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api_client.dart';
import '../models.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _api = ApiClient();
  final _picker = ImagePicker();
  final _mobileController = TextEditingController();
  final _addressController = TextEditingController();

  late Future<CourierProfile> _future;
  File? _newIdDocument;
  File? _newDrivingLicense;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void dispose() {
    _mobileController.dispose();
    _addressController.dispose();
    super.dispose();
  }

  Future<CourierProfile> _load() async {
    final profile = await _api.getProfile();
    _mobileController.text = profile.mobile;
    _addressController.text = profile.address;
    return profile;
  }

  Future<void> _refresh() async {
    final next = _load();
    setState(() => _future = next);
    await next;
  }

  Future<void> _pickPhoto(void Function(File) onPicked) async {
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
    if (source == null) return;
    final picked = await _picker.pickImage(source: source, maxWidth: 1600, imageQuality: 85);
    if (picked != null) setState(() => onPicked(File(picked.path)));
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await _api.updateProfile(
        mobile: _mobileController.text.trim(),
        address: _addressController.text.trim(),
        idDocument: _newIdDocument,
        drivingLicense: _newDrivingLicense,
      );
      _newIdDocument = null;
      _newDrivingLicense = null;
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Profile updated.')),
      );
      await _refresh();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Could not reach the server — check your connection.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My Profile')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<CourierProfile>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  const SizedBox(height: 60),
                  Center(child: Text('${snapshot.error}')),
                  const SizedBox(height: 12),
                  Center(child: FilledButton(onPressed: _refresh, child: const Text('Retry'))),
                ],
              );
            }
            final profile = snapshot.data!;
            return ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(profile.fullName, style: Theme.of(context).textTheme.titleLarge),
                Text(profile.email, style: const TextStyle(color: Colors.grey)),
                const SizedBox(height: 12),
                _VerificationBadge(status: profile.verificationStatus),
                if (profile.verificationNote.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(profile.verificationNote, style: const TextStyle(color: Colors.grey)),
                ],
                const SizedBox(height: 24),
                TextField(
                  controller: _mobileController,
                  decoration: const InputDecoration(labelText: 'Phone number', border: OutlineInputBorder()),
                  keyboardType: TextInputType.phone,
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _addressController,
                  decoration: const InputDecoration(labelText: 'Address', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 24),
                Text('Documents', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text(
                  'Uploading a new photo sends it for re-verification.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                _DocumentRow(
                  label: 'Identity card',
                  hasExisting: profile.hasIdDocument,
                  newFile: _newIdDocument,
                  onTap: () => _pickPhoto((f) => _newIdDocument = f),
                ),
                const SizedBox(height: 8),
                _DocumentRow(
                  label: 'Driving license',
                  hasExisting: profile.hasDrivingLicense,
                  newFile: _newDrivingLicense,
                  onTap: () => _pickPhoto((f) => _newDrivingLicense = f),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 16),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: _saving ? null : _save,
                  child: _saving
                      ? const SizedBox(
                          height: 20, width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Save changes'),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _VerificationBadge extends StatelessWidget {
  final String status;
  const _VerificationBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    final (color, label, icon) = switch (status) {
      'verified' => (Colors.green, 'Verified', Icons.check_circle),
      'rejected' => (Colors.red, 'Rejected', Icons.cancel),
      _ => (Colors.orange, 'Pending verification', Icons.hourglass_top),
    };
    return Chip(
      avatar: Icon(icon, color: Colors.white, size: 18),
      label: Text(label, style: const TextStyle(color: Colors.white)),
      backgroundColor: color,
    );
  }
}

class _DocumentRow extends StatelessWidget {
  final String label;
  final bool hasExisting;
  final File? newFile;
  final VoidCallback onTap;
  const _DocumentRow({required this.label, required this.hasExisting, required this.newFile, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final status = newFile != null
        ? 'New photo selected'
        : hasExisting
            ? 'On file'
            : 'Not submitted';
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(
        newFile != null || hasExisting ? Icons.check_circle_outline : Icons.error_outline,
        color: newFile != null ? Colors.blue : (hasExisting ? Colors.green : Colors.grey),
      ),
      title: Text(label),
      subtitle: Text(status),
      trailing: OutlinedButton(onPressed: onTap, child: const Text('Replace')),
    );
  }
}
