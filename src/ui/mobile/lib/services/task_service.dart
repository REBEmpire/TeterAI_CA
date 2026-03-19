import 'dart:convert';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'auth_service.dart';

/// Live stream of reviewable tasks from Firestore.
Stream<List<Map<String, dynamic>>> taskQueueStream() {
  return FirebaseFirestore.instance
      .collection('tasks')
      .where('status', whereIn: ['STAGED_FOR_REVIEW', 'ESCALATED_TO_HUMAN'])
      .snapshots()
      .map((snapshot) {
        final docs = snapshot.docs
            .map((d) => {...d.data(), 'task_id': d.id})
            .toList();

        // Sort: HIGH > MEDIUM > LOW, then oldest first
        const urgencyOrder = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2};
        docs.sort((a, b) {
          final ua = urgencyOrder[a['urgency']] ?? 9;
          final ub = urgencyOrder[b['urgency']] ?? 9;
          if (ua != ub) return ua.compareTo(ub);
          final ta = (a['created_at'] as String?) ?? '';
          final tb = (b['created_at'] as String?) ?? '';
          return ta.compareTo(tb);
        });

        return docs;
      });
}

class TaskService {
  final AuthService _auth;
  final String _apiBase;

  TaskService({required AuthService auth, required String apiBase})
      : _auth = auth,
        _apiBase = apiBase;

  Future<Map<String, String>> _headers() async {
    final token = await _auth.getToken();
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Future<Map<String, dynamic>> getTask(String taskId) async {
    final resp = await http.get(
      Uri.parse('$_apiBase/api/v1/tasks/$taskId'),
      headers: await _headers(),
    );
    if (resp.statusCode != 200) throw Exception('Failed to load task');
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  Future<void> approveTask(String taskId) async {
    final resp = await http.post(
      Uri.parse('$_apiBase/api/v1/tasks/$taskId/approve'),
      headers: await _headers(),
      body: jsonEncode({'edited_draft': null}),
    );
    if (resp.statusCode != 200) throw Exception('Approval failed');
  }

  Future<void> rejectTask(String taskId, String reason, {String? notes}) async {
    final resp = await http.post(
      Uri.parse('$_apiBase/api/v1/tasks/$taskId/reject'),
      headers: await _headers(),
      body: jsonEncode({'reason': reason, 'notes': notes}),
    );
    if (resp.statusCode != 200) throw Exception('Rejection failed');
  }
}

final taskServiceProvider = Provider((ref) => TaskService(
      auth: ref.read(authServiceProvider),
      apiBase: const String.fromEnvironment(
        'API_BASE',
        defaultValue: 'https://teterai-ca.run.app',
      ),
    ));
