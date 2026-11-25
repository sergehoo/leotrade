import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/features/auth/domain/models.dart';

void main() {
  test('MfaRequired et LoginSucceeded sont bien distincts', () {
    // Le routeur et le contrôleur s'appuient sur ce type scellé pour ne
    // jamais considérer un défi MFA comme une connexion réussie.
    const LoginResult challenge = MfaRequired('jeton');
    const LoginResult success = LoginSucceeded(
      CurrentUser(
        id: 1,
        email: 'a@b.test',
        firstName: '',
        lastName: '',
        kycStatus: KycStatus.notStarted,
        kycRejectionReason: '',
        mfaEnabled: true,
        emailVerified: true,
        capabilities: Capabilities.closed,
      ),
    );

    expect(challenge, isA<MfaRequired>());
    expect(challenge, isNot(isA<LoginSucceeded>()));
    expect(success, isA<LoginSucceeded>());
  });

  test('displayName retombe sur l\'email quand le nom est vide', () {
    const user = CurrentUser(
      id: 1,
      email: 'trader@leotrade.test',
      firstName: '',
      lastName: '',
      kycStatus: KycStatus.approved,
      kycRejectionReason: '',
      mfaEnabled: false,
      emailVerified: true,
      capabilities: Capabilities.closed,
    );
    expect(user.displayName, 'trader@leotrade.test');
  });
}
