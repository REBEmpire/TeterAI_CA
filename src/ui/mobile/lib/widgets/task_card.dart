import 'package:flutter/material.dart';

import '../theme/teter_theme.dart';

class UrgencyBadge extends StatelessWidget {
  final String urgency;
  const UrgencyBadge({super.key, required this.urgency});

  @override
  Widget build(BuildContext context) {
    final (bg, text) = switch (urgency) {
      'HIGH' => (TeterColors.urgencyHighBg, TeterColors.urgencyHigh),
      'MEDIUM' => (TeterColors.urgencyMediumBg, TeterColors.urgencyMedium),
      _ => (TeterColors.urgencyLowBg, TeterColors.urgencyLow),
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: text, shape: BoxShape.circle),
          ),
          const SizedBox(width: 5),
          Text(
            urgency,
            style: TextStyle(
              color: text,
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}

class ConfidenceBadge extends StatelessWidget {
  final double score;
  const ConfidenceBadge({super.key, required this.score});

  @override
  Widget build(BuildContext context) {
    final color = TeterColors.forConfidence(score);
    final pct = (score * 100).round();
    return Text(
      '$pct%',
      style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700),
    );
  }
}

class TaskCard extends StatelessWidget {
  final Map<String, dynamic> task;
  final VoidCallback onTap;

  const TaskCard({super.key, required this.task, required this.onTap});

  String _ageLabel() {
    final createdAt = task['created_at'] as String?;
    if (createdAt == null) return '';
    final dt = DateTime.tryParse(createdAt);
    if (dt == null) return '';
    final diff = DateTime.now().difference(dt);
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }

  @override
  Widget build(BuildContext context) {
    final docType = task['document_type'] as String? ?? 'UNKNOWN';
    final docNum = task['document_number'] as String?;
    final project = task['project_number'] as String?;
    final sender = task['sender_name'] as String?;
    final subject = task['subject'] as String?;
    final urgency = task['urgency'] as String? ?? 'LOW';
    final confidence = (task['classification_confidence'] as num?)?.toDouble();
    final isEscalated = task['status'] == 'ESCALATED_TO_HUMAN';

    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Top row: urgency + doc type + age
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  UrgencyBadge(urgency: urgency),
                  if (isEscalated) ...[
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: Colors.purple.shade50,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        '⚠ Escalated',
                        style: TextStyle(
                          color: Colors.purple.shade700,
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                  const Spacer(),
                  Text(_ageLabel(), style: const TextStyle(fontSize: 11, color: TeterColors.grayText)),
                ],
              ),
              const SizedBox(height: 8),

              // Doc type + number
              Text(
                '$docType${docNum != null ? ' — $docNum' : ''}',
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  color: TeterColors.dark,
                  fontSize: 14,
                ),
              ),

              // Sender + project
              if (sender != null || project != null) ...[
                const SizedBox(height: 4),
                Text(
                  [if (sender != null) sender, if (project != null) project].join(' · '),
                  style: const TextStyle(fontSize: 13, color: TeterColors.grayText),
                ),
              ],

              // Subject
              if (subject != null) ...[
                const SizedBox(height: 4),
                Text(
                  subject,
                  style: const TextStyle(fontSize: 12, color: TeterColors.grayText),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],

              // Confidence
              if (confidence != null) ...[
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Text(
                      'Confidence  ',
                      style: TextStyle(fontSize: 11, color: TeterColors.grayText),
                    ),
                    ConfidenceBadge(score: confidence),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
