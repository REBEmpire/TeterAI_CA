import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;

const _tokenKey = 'teterai_token';

class AuthService {
  final _storage = const FlutterSecureStorage();
  final _googleSignIn = GoogleSignIn(
    scopes: ['email', 'profile'],
    hostedDomain: 'teter.com',
  );

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  Future<Map<String, dynamic>?> signIn(String apiBase) async {
    final googleUser = await _googleSignIn.signIn();
    if (googleUser == null) return null; // User cancelled

    final googleAuth = await googleUser.authentication;
    final idToken = googleAuth.idToken;
    if (idToken == null) return null;

    // Exchange Google ID token for our JWT
    final resp = await http.post(
      Uri.parse('$apiBase/api/v1/auth/google/callback'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'id_token': idToken}),
    );

    if (resp.statusCode != 200) return null;
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    final jwt = data['access_token'] as String;
    await _storage.write(key: _tokenKey, value: jwt);
    return data['user'] as Map<String, dynamic>?;
  }

  Future<void> signOut() async {
    await _googleSignIn.signOut();
    await _storage.delete(key: _tokenKey);
  }

  Future<String?> getToken() => _storage.read(key: _tokenKey);

  Future<bool> isSignedIn() async {
    final token = await getToken();
    return token != null;
  }
}

final authServiceProvider = Provider((_) => AuthService());
