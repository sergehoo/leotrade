import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import 'auth_controller.dart';

class LoginScreen extends ConsumerWidget {
  const LoginScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final awaitingMfa =
        ref.watch(authControllerProvider.select((s) => s.awaitingMfa));

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('LeoTrade', style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 6),
                  const Text(
                    'Trading assisté par intelligence artificielle',
                    style: TextStyle(color: AppColors.muted),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 32),
                  awaitingMfa ? const _MfaForm() : const _CredentialsForm(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _CredentialsForm extends ConsumerStatefulWidget {
  const _CredentialsForm();

  @override
  ConsumerState<_CredentialsForm> createState() => _CredentialsFormState();
}

class _CredentialsFormState extends ConsumerState<_CredentialsForm> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _submitting = false;
  bool _obscure = true;
  String? _error;
  String? _errorCode;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _submitting = true;
      _error = null;
      _errorCode = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .signIn(_email.text, _password.text);
      // La navigation est pilotée par le routeur, qui observe l'état d'auth.
    } on ApiError catch (error) {
      if (mounted) {
        setState(() {
          _error = error.message;
          _errorCode = error.code;
        });
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) ...[
            _ErrorBox(
              message: _error!,
              hint: _errorCode == 'EMAIL_NOT_VERIFIED'
                  ? 'Ouvrez le lien de vérification reçu par email, puis réessayez.'
                  : null,
            ),
            const SizedBox(height: 16),
          ],
          TextFormField(
            controller: _email,
            keyboardType: TextInputType.emailAddress,
            autocorrect: false,
            autofillHints: const [AutofillHints.email],
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Adresse email'),
            validator: (value) {
              final text = (value ?? '').trim();
              if (text.isEmpty) return 'Adresse email requise.';
              if (!text.contains('@')) return 'Adresse email invalide.';
              return null;
            },
          ),
          const SizedBox(height: 14),
          TextFormField(
            controller: _password,
            obscureText: _obscure,
            autofillHints: const [AutofillHints.password],
            textInputAction: TextInputAction.done,
            onFieldSubmitted: (_) => _submit(),
            decoration: InputDecoration(
              labelText: 'Mot de passe',
              suffixIcon: IconButton(
                onPressed: () => setState(() => _obscure = !_obscure),
                icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility),
                tooltip: _obscure ? 'Afficher' : 'Masquer',
              ),
            ),
            validator: (value) =>
                (value ?? '').isEmpty ? 'Mot de passe requis.' : null,
          ),
          const SizedBox(height: 22),
          FilledButton(
            onPressed: _submitting ? null : _submit,
            child: _submitting
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Se connecter'),
          ),
        ],
      ),
    );
  }
}

class _MfaForm extends ConsumerStatefulWidget {
  const _MfaForm();

  @override
  ConsumerState<_MfaForm> createState() => _MfaFormState();
}

class _MfaFormState extends ConsumerState<_MfaForm> {
  final _code = TextEditingController();
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_code.text.trim().length < 6) {
      setState(() => _error = 'Le code comporte au moins 6 caractères.');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).submitMfa(_code.text);
    } on ApiError catch (error) {
      if (mounted) {
        setState(() => _error = error.message);
        _code.clear();
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.shield_outlined, size: 18, color: AppColors.primary),
            SizedBox(width: 8),
            Text('Vérification en deux étapes',
                style: TextStyle(fontWeight: FontWeight.w600)),
          ],
        ),
        const SizedBox(height: 8),
        const Text(
          "Saisissez le code de votre application d'authentification, "
          'ou l\'un de vos codes de récupération.',
          style: TextStyle(color: AppColors.muted, height: 1.45),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 22),
        if (_error != null) ...[
          _ErrorBox(message: _error!),
          const SizedBox(height: 16),
        ],
        TextField(
          controller: _code,
          keyboardType: TextInputType.number,
          autofocus: true,
          textAlign: TextAlign.center,
          autofillHints: const [AutofillHints.oneTimeCode],
          style: const TextStyle(fontSize: 20, letterSpacing: 6),
          decoration: const InputDecoration(labelText: 'Code de vérification'),
          onSubmitted: (_) => _submit(),
        ),
        const SizedBox(height: 22),
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _submitting
                    ? null
                    : () => ref.read(authControllerProvider.notifier).cancelMfa(),
                child: const Text('Retour'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: FilledButton(
                onPressed: _submitting ? null : _submit,
                child: _submitting
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Valider'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox({required this.message, this.hint});

  final String message;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.loss.withValues(alpha: 0.10),
        border: Border.all(color: AppColors.loss.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(message, style: const TextStyle(height: 1.4)),
          if (hint != null) ...[
            const SizedBox(height: 6),
            Text(hint!, style: const TextStyle(color: AppColors.muted, height: 1.4)),
          ],
        ],
      ),
    );
  }
}
