import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/states.dart';
import '../data/brokers_repository.dart';
import '../domain/models.dart';

/// Exigences par broker, miroir de `BrokerAccount.clean()` côté serveur.
/// Le serveur reste l'autorité : ce tableau évite un aller-retour inutile
/// et n'affiche que les champs pertinents.
class _BrokerSpec {
  const _BrokerSpec({required this.fields, required this.secrets});

  final List<_FieldSpec> fields;
  final List<SecretField> secrets;
}

class _FieldSpec {
  const _FieldSpec(this.key, this.label, {this.required = false, this.hint});

  final String key;
  final String label;
  final bool required;
  final String? hint;
}

const _specs = <BrokerKind, _BrokerSpec>{
  BrokerKind.binance: _BrokerSpec(
    fields: [],
    secrets: [SecretField.apiKey, SecretField.apiSecret],
  ),
  BrokerKind.mt5: _BrokerSpec(
    fields: [
      _FieldSpec('login', 'Login', required: true, hint: '12345678'),
      _FieldSpec('server', 'Serveur', required: true, hint: 'ICMarketsSC-Demo'),
      _FieldSpec('terminal_path', 'Chemin du terminal'),
    ],
    secrets: [SecretField.password],
  ),
  BrokerKind.deriv: _BrokerSpec(
    fields: [
      _FieldSpec('deriv_app_id', 'App ID', required: true, hint: '1089'),
      _FieldSpec('deriv_currency', 'Devise', required: true, hint: 'USD'),
      _FieldSpec('deriv_account_type', 'Type de compte'),
    ],
    secrets: [SecretField.derivToken],
  ),
};

/// Ouvre la fiche de création ou de modification. Renvoie `true` si le
/// serveur a accepté l'enregistrement.
Future<bool?> showBrokerFormSheet(
  BuildContext context, {
  BrokerAccount? account,
  required bool canTradeLive,
}) {
  return showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
    ),
    builder: (_) => _BrokerFormSheet(account: account, canTradeLive: canTradeLive),
  );
}

class _BrokerFormSheet extends ConsumerStatefulWidget {
  const _BrokerFormSheet({this.account, required this.canTradeLive});

  final BrokerAccount? account;
  final bool canTradeLive;

  @override
  ConsumerState<_BrokerFormSheet> createState() => _BrokerFormSheetState();
}

class _BrokerFormSheetState extends ConsumerState<_BrokerFormSheet> {
  final _formKey = GlobalKey<FormState>();
  final _controllers = <String, TextEditingController>{};
  final _secretControllers = <SecretField, TextEditingController>{};

  late BrokerKind _broker;
  late TradingMode _mode;
  late bool _isActive;
  late bool _isDefault;

  bool _submitting = false;
  String? _formError;
  Map<String, List<String>> _fieldErrors = const {};

  bool get _isEdit => widget.account != null;

  @override
  void initState() {
    super.initState();
    final account = widget.account;
    _broker = account?.broker ?? BrokerKind.deriv;
    _mode = account?.mode ?? TradingMode.paper;
    _isActive = account?.isActive ?? true;
    _isDefault = account?.isDefault ?? false;

    _controllers['name'] = TextEditingController(text: account?.name ?? '');
    _controllers['login'] = TextEditingController(text: account?.login ?? '');
    _controllers['server'] = TextEditingController(text: account?.server ?? '');
    _controllers['terminal_path'] =
        TextEditingController(text: account?.terminalPath ?? '');
    _controllers['deriv_app_id'] =
        TextEditingController(text: account?.derivAppId ?? '');
    _controllers['deriv_currency'] =
        TextEditingController(text: account?.derivCurrency ?? 'USD');
    _controllers['deriv_account_type'] =
        TextEditingController(text: account?.derivAccountType ?? '');
    _controllers['notes'] = TextEditingController(text: account?.notes ?? '');

    // Les champs de secret partent toujours vides : une valeur enregistrée
    // n'est jamais renvoyée par le serveur, donc jamais préremplie ici.
    for (final field in SecretField.values) {
      _secretControllers[field] = TextEditingController();
    }
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    for (final controller in _secretControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  _BrokerSpec get _spec => _specs[_broker] ?? const _BrokerSpec(fields: [], secrets: []);

  String? _trimmed(String key) {
    final value = _controllers[key]?.text.trim() ?? '';
    return value.isEmpty ? null : value;
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() {
      _submitting = true;
      _formError = null;
      _fieldErrors = const {};
    });

    final draft = BrokerAccountDraft(
      name: _controllers['name']!.text.trim(),
      broker: _broker,
      mode: _mode,
      login: _trimmed('login'),
      server: _trimmed('server'),
      terminalPath: _trimmed('terminal_path'),
      derivAppId: _trimmed('deriv_app_id'),
      derivCurrency: _trimmed('deriv_currency'),
      derivAccountType: _trimmed('deriv_account_type'),
      isActive: _isActive,
      isDefault: _isDefault,
      notes: _controllers['notes']!.text.trim(),
      secrets: {
        for (final field in _spec.secrets)
          if (_secretControllers[field]!.text.isNotEmpty)
            field: _secretControllers[field]!.text,
      },
    );

    final repository = ref.read(brokersRepositoryProvider);
    try {
      if (_isEdit) {
        await repository.update(widget.account!.id, draft);
      } else {
        await repository.create(draft);
      }
      if (mounted) Navigator.of(context).pop(true);
    } on ApiError catch (error) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _fieldErrors = error.fields ?? const {};
        _formError = error.fields == null ? error.message : null;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final liveBlocked = _mode == TradingMode.live && !widget.canTradeLive;
    final insets = MediaQuery.viewInsetsOf(context).bottom;

    return Padding(
      padding: EdgeInsets.only(bottom: insets),
      child: DraggableScrollableSheet(
        initialChildSize: 0.92,
        minChildSize: 0.5,
        maxChildSize: 0.96,
        expand: false,
        builder: (context, scrollController) => Form(
          key: _formKey,
          child: ListView(
            controller: scrollController,
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
            children: [
              Center(
                child: Container(
                  width: 38,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.border,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 18),
              Text(
                _isEdit ? 'Modifier « ${widget.account!.name} »' : 'Nouveau compte broker',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 6),
              Text(
                _isEdit
                    ? 'Laisse un champ d\'identifiant vide pour conserver la valeur chiffrée existante.'
                    : 'Les identifiants sont chiffrés à l\'enregistrement et ne sont jamais réaffichés.',
                style: const TextStyle(color: AppColors.muted, height: 1.4),
              ),
              const SizedBox(height: 20),

              if (_formError != null) ...[
                NoticeBanner(message: _formError!, tone: NoticeTone.danger),
                const SizedBox(height: 16),
              ],

              _field('name', 'Nom', required: true, hint: 'Deriv principal'),
              const SizedBox(height: 14),

              DropdownButtonFormField<BrokerKind>(
                initialValue: _broker,
                decoration: const InputDecoration(labelText: 'Broker'),
                // Changer de broker reviendrait à changer la nature du
                // compte : on crée un autre compte à la place.
                onChanged: _isEdit
                    ? null
                    : (value) => setState(() => _broker = value ?? _broker),
                items: const [
                  DropdownMenuItem(value: BrokerKind.deriv, child: Text('Deriv')),
                  DropdownMenuItem(value: BrokerKind.mt5, child: Text('MetaTrader 5')),
                  DropdownMenuItem(value: BrokerKind.binance, child: Text('Binance')),
                ],
              ),
              const SizedBox(height: 14),

              DropdownButtonFormField<TradingMode>(
                initialValue: _mode,
                decoration: const InputDecoration(labelText: 'Mode'),
                onChanged: (value) => setState(() => _mode = value ?? _mode),
                items: const [
                  DropdownMenuItem(
                    value: TradingMode.paper,
                    child: Text('Paper — simulation'),
                  ),
                  DropdownMenuItem(
                    value: TradingMode.live,
                    child: Text('Live — argent réel'),
                  ),
                ],
              ),

              if (liveBlocked) ...[
                const SizedBox(height: 14),
                const NoticeBanner(
                  tone: NoticeTone.warning,
                  message:
                      'Le mode Live exige un KYC approuvé. Tant que ton dossier '
                      'n\'est pas validé, l\'enregistrement sera refusé — le mode '
                      'Paper reste disponible sans restriction.',
                ),
              ],

              for (final field in _spec.fields) ...[
                const SizedBox(height: 14),
                _field(field.key, field.label,
                    required: field.required, hint: field.hint),
              ],

              if (_spec.secrets.isNotEmpty) ...[
                const SizedBox(height: 22),
                const Text(
                  'Identifiants — chiffrés, jamais réaffichés',
                  style: TextStyle(
                    color: AppColors.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                for (final secret in _spec.secrets) ...[
                  const SizedBox(height: 14),
                  _secretField(secret),
                ],
              ],

              const SizedBox(height: 22),
              SwitchListTile.adaptive(
                value: _isActive,
                onChanged: (value) => setState(() => _isActive = value),
                contentPadding: EdgeInsets.zero,
                title: const Text('Compte actif'),
                subtitle: const Text(
                  'Un compte inactif n\'est jamais sollicité par l\'exécution.',
                  style: TextStyle(color: AppColors.muted, fontSize: 12),
                ),
              ),
              SwitchListTile.adaptive(
                value: _isDefault,
                onChanged: (value) => setState(() => _isDefault = value),
                contentPadding: EdgeInsets.zero,
                title: const Text('Compte par défaut'),
                subtitle: const Text(
                  'Utilisé quand aucun compte n\'est explicitement choisi.',
                  style: TextStyle(color: AppColors.muted, fontSize: 12),
                ),
              ),

              const SizedBox(height: 14),
              _field('notes', 'Notes (facultatif)', maxLines: 2),

              const SizedBox(height: 26),
              FilledButton(
                onPressed: _submitting ? null : _submit,
                child: _submitting
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Text(_isEdit ? 'Enregistrer' : 'Créer le compte'),
              ),
              const SizedBox(height: 10),
              TextButton(
                onPressed: _submitting ? null : () => Navigator.of(context).pop(),
                child: const Text('Annuler'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _field(
    String key,
    String label, {
    bool required = false,
    String? hint,
    int maxLines = 1,
  }) {
    return TextFormField(
      controller: _controllers[key],
      maxLines: maxLines,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        errorText: _fieldErrors[key]?.join(' '),
      ),
      validator: required
          ? (value) => (value == null || value.trim().isEmpty)
              ? '$label obligatoire.'
              : null
          : null,
    );
  }

  Widget _secretField(SecretField field) {
    final state = widget.account?.secretState(field);
    final configured = state?.configured ?? false;
    final key = secretFieldWire(field);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextFormField(
          controller: _secretControllers[field],
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(
            labelText: secretFieldLabel(field),
            hintText: configured ? '•••••••• (inchangé)' : null,
            errorText: _fieldErrors[key]?.join(' '),
          ),
          validator: (value) {
            // À la création, un secret requis est obligatoire. En
            // modification, le laisser vide conserve l'existant.
            if (_isEdit || !_spec.secrets.contains(field)) return null;
            return (value == null || value.isEmpty)
                ? '${secretFieldLabel(field)} obligatoire.'
                : null;
          },
        ),
        if (configured)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              // La date vient du serveur et était ignorée. Elle est la
              // seule façon de savoir si le secret enregistré est celui
              // qu'on croit — après une rotation de clés chez le broker,
              // « Enregistré » tout seul ne dit rien.
              state?.updatedAt != null
                  ? 'Enregistré le '
                      '${DateFormat('dd/MM/yyyy', 'fr_FR').format(state!.updatedAt!.toLocal())}. '
                      'Saisis une valeur pour le remplacer.'
                  : 'Enregistré. Saisis une valeur pour le remplacer.',
              style: const TextStyle(color: AppColors.muted, fontSize: 12),
            ),
          ),
      ],
    );
  }
}
