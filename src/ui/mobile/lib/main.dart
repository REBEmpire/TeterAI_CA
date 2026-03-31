import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'screens/login_screen.dart';
import 'theme/teter_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp();
  runApp(const ProviderScope(child: TeterAIApp()));
}

class TeterAIApp extends StatelessWidget {
  const TeterAIApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TeterAI',
      theme: teterTheme,
      debugShowCheckedModeBanner: false,
      home: const LoginScreen(),
    );
  }
}
