import java.util.Properties

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Matériel de signature, hors du dépôt.
//
// `key.properties` est ignoré par git : une clé de publication versionnée
// permet à quiconque lit le dépôt de signer une application qui se fera
// passer pour celle-ci.
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        keystorePropertiesFile.inputStream().use { load(it) }
    }
}
val hasReleaseKeystore = keystorePropertiesFile.exists()

android {
    // Le projet s'appelle LeoTrade. L'identifiant d'origine, com.lyneci.lyneci,
    // était celui du gabarit Flutter — son TODO « Specify your own unique
    // Application ID » n'avait jamais été traité.
    //
    // Le renommer ne casse rien ici : aucun keystore de publication n'existe,
    // les builds release étaient signés avec les clés de debug (donc non
    // distribuables), et le numéro de build est resté à 1. Il n'existe aucune
    // installation à mettre à jour.
    namespace = "com.leotrade.app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        applicationId = "com.leotrade.app"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseKeystore) {
            create("release") {
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
                storeFile = keystoreProperties.getProperty("storeFile")?.let { file(it) }
                storePassword = keystoreProperties.getProperty("storePassword")
            }
        }
    }

    buildTypes {
        release {
            // Sans `key.properties`, on retombe sur les clés de debug pour que
            // `flutter run --release` reste utilisable en développement — mais
            // l'avertissement ci-dessous est délibérément bruyant : un APK
            // signé en debug s'installe, se lance, et ne peut JAMAIS être
            // publié ni mis à jour. Sans message, il passe pour un binaire de
            // production.
            signingConfig = if (hasReleaseKeystore) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

if (!hasReleaseKeystore) {
    logger.warn(
        "\n" +
            "*********************************************************************\n" +
            "  LeoTrade : android/key.properties est absent.\n" +
            "  Les builds release seront signés avec les CLÉS DE DEBUG.\n" +
            "  Un tel binaire n'est ni publiable ni mettable à jour.\n" +
            "  Voir mobile/README.md, section « Signature de publication ».\n" +
            "*********************************************************************\n",
    )
}

flutter {
    source = "../.."
}
