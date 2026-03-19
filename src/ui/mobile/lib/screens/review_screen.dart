import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/task_service.dart';
import '../theme/teter_theme.dart';
import '../widgets/task_card.dart';

const _rejectionReasons = [
  ('CitationError', 'Citation Error'),
  ('ContentError', 'Content Error'),
  ('ToneStyle', 'Tone / Style'),
  ('MissingInfo', 'Missing Information'),
  ('ScopeIssue', 'Scope Issue'),
  ('Other', 'Other'),
];

class ReviewScreen extends ConsumerStatefulWidget {
  final Map<String, dynamic> task;
  const ReviewScreen({super.key, required this.task});

  @override
  ConsumerState<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends ConsumerState<ReviewScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabs;
  bool _acting = false;
  String? _actionError;

  // Full task detail (loaded on mount)
  Map<String, dynamic>? _detail;

  @override
  void initState() {
    super.initState();
    // Tablet: 2 tabs side-by-side; phone: 2 tabs stacked
    _tabs = TabController(length: 2, vsync: this);
    _loadDetail();
  }

  Future<void> _loadDetail() async {
    try {
      final detail = await ref
          .read(taskServiceProvider)
          .getTask(widget.task['task_id'] as String);
      if (mounted) setState(() => _detail = detail);
    } catch (_) {}
  }

  Future<void> _approve() async {
    setState(() => _acting = true);
    try {
      await ref.read(taskServiceProvider).approveTask(widget.task['task_id'] as String);
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      if (mounted) setState(() => _actionError = 'Approval failed: $e');
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  Future<void> _showRejectDialog() async {
    String selectedReason = 'ContentError';
    String notes = '';

    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Row(
          children: [
            Container(
              width: 3,
              height: 20,
              margin: const EdgeInsets.only(right: 10),
              decoration: BoxDecoration(
                color: TeterColors.orange,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const Text(
              'Reject Draft',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        content: StatefulBuilder(
          builder: (ctx, setStateLocal) => Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Rejection Reason *',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: TeterColors.grayText,
                  letterSpacing: 0.5,
                ),
              ),
              const SizedBox(height: 6),
              DropdownButtonFormField<String>(
                value: selectedReason,
                items: _rejectionReasons
                    .map((r) => DropdownMenuItem(value: r.$1, child: Text(r.$2)))
                    .toList(),
                onChanged: (v) => setStateLocal(() => selectedReason = v ?? selectedReason),
                decoration: const InputDecoration(isDense: true),
              ),
              const SizedBox(height: 14),
              const Text(
                'Notes (optional)',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: TeterColors.grayText,
                  letterSpacing: 0.5,
                ),
              ),
              const SizedBox(height: 6),
              TextField(
                maxLines: 3,
                decoration: const InputDecoration(
                  hintText: 'Feedback for the agent…',
                ),
                onChanged: (v) => notes = v,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () async {
              Navigator.of(ctx).pop();
              setState(() => _acting = true);
              try {
                await ref.read(taskServiceProvider).rejectTask(
                      widget.task['task_id'] as String,
                      selectedReason,
                      notes: notes.isEmpty ? null : notes,
                    );
                if (mounted) Navigator.of(context).pop();
              } catch (e) {
                if (mounted)
                  setState(() => _actionError = 'Rejection failed: $e');
              } finally {
                if (mounted) setState(() => _acting = false);
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: TeterColors.urgencyHigh),
            child: const Text('Reject and Send Back'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final task = _detail ?? widget.task;
    final docType = task['document_type'] as String? ?? 'UNKNOWN';
    final docNum = task['document_number'] as String?;
    final urgency = task['urgency'] as String? ?? 'LOW';
    final draft = task['draft_content'] as String? ?? '';
    final confidence = (task['confidence_score'] as num?)?.toDouble();

    final sourceEmail = task['source_email'] as Map<String, dynamic>?;

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            UrgencyBadge(urgency: urgency),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                '$docType${docNum != null ? ' — $docNum' : ''}',
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 14),
              ),
            ),
          ],
        ),
        bottom: TabBar(
          controller: _tabs,
          tabs: const [
            Tab(text: 'Agent Draft'),
            Tab(text: 'Source'),
          ],
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: TabBarView(
              controller: _tabs,
              children: [
                // ── Draft tab ─────────────────────────────────
                SingleChildScrollView(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Confidence
                      if (confidence != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: Row(
                            children: [
                              const Text(
                                'Confidence  ',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: TeterColors.grayText,
                                ),
                              ),
                              ConfidenceBadge(score: confidence),
                            ],
                          ),
                        ),

                      // Draft content
                      SelectableText(
                        draft.isNotEmpty
                            ? draft
                            : 'No draft content available.',
                        style: const TextStyle(
                          fontSize: 13,
                          height: 1.6,
                          color: TeterColors.dark,
                          fontFamily: 'Arial',
                        ),
                      ),
                    ],
                  ),
                ),

                // ── Source tab ────────────────────────────────
                SingleChildScrollView(
                  padding: const EdgeInsets.all(16),
                  child: sourceEmail != null
                      ? Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (sourceEmail['from'] != null) ...[
                              _metaRow('From', sourceEmail['from'] as String),
                              const SizedBox(height: 8),
                            ],
                            if (sourceEmail['subject'] != null) ...[
                              _metaRow('Subject', sourceEmail['subject'] as String,
                                  bold: true),
                              const SizedBox(height: 8),
                            ],
                            const Divider(),
                            const SizedBox(height: 8),
                            SelectableText(
                              sourceEmail['body'] as String? ?? '',
                              style: const TextStyle(
                                fontSize: 13,
                                height: 1.6,
                                color: TeterColors.dark,
                              ),
                            ),
                          ],
                        )
                      : const Text(
                          'Source document not available.',
                          style: TextStyle(color: TeterColors.grayText),
                        ),
                ),
              ],
            ),
          ),

          // Action error
          if (_actionError != null)
            Container(
              color: const Color(0xFFFFEBEE),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Text(
                _actionError!,
                style: const TextStyle(
                    color: TeterColors.urgencyHigh, fontSize: 12),
              ),
            ),

          // Action bar
          Container(
            color: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: SafeArea(
              top: false,
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _acting ? null : _showRejectDialog,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: TeterColors.urgencyHigh,
                        side: const BorderSide(color: TeterColors.urgencyHigh),
                      ),
                      child: const Text('Reject'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: ElevatedButton(
                      onPressed: _acting ? null : _approve,
                      child: _acting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Text('Approve'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _metaRow(String label, String value, {bool bold = false}) {
    return RichText(
      text: TextSpan(
        style: const TextStyle(
            color: TeterColors.dark, fontFamily: 'Arial', fontSize: 13),
        children: [
          TextSpan(
            text: '$label: ',
            style: const TextStyle(
                fontWeight: FontWeight.w600, color: TeterColors.grayText),
          ),
          TextSpan(
            text: value,
            style: TextStyle(
                fontWeight: bold ? FontWeight.w600 : FontWeight.normal),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }
}
