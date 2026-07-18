# TimorMart mobile app

Android and iOS apps built with [Capacitor](https://capacitorjs.com/), wrapping
the live site (`https://timormart.onrender.com`, set in `capacitor.config.json`)
in a native shell. There is no separate mobile codebase to maintain — every
change to the Django site (new features, translations, bug fixes) shows up in
the app automatically, the next time it's opened. Only truly native concerns
(app icon, splash screen, back-button behavior, status bar color, push
notifications later) live here.

The site itself is Capacitor-aware in one small, guarded place:
[templates/shared/base.html](../templates/shared/base.html) — a script at the
bottom checks `window.Capacitor` (only defined when running inside the app)
and wires up the Android back button, status bar color, and splash-screen
dismissal. It's a complete no-op for every regular browser visitor.

## Prerequisites already confirmed on this machine

- Node.js / npm — installed
- Android Studio + Android SDK (`android-36`, build-tools 35/36) — installed
- **iOS builds require Xcode on macOS.** There is no way around this — Apple
  does not allow building, signing, or submitting iOS apps from Windows or
  Linux. The `ios/` folder here is fully scaffolded and ready to open in
  Xcode on a Mac (or a cloud Mac CI service like Codemagic/Bitrise/GitHub
  Actions macOS runners) — nothing further needs to change in this repo for
  that, just the actual build/sign/submit steps.

## Common commands

```
cd mobile
npx cap sync            # re-copy config + plugin changes into android/ and ios/
npx cap open android     # opens the Android project in Android Studio
npx cap open ios         # opens the iOS project in Xcode (Mac only)
```

You do **not** need to run `cap sync` after changing Django templates/views —
only after changing `capacitor.config.json` or installing/upgrading a
Capacitor plugin.

## Building an Android APK from the command line

Android Studio's bundled JDK works well as `JAVA_HOME`:

```
export JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"
export ANDROID_HOME="/c/Users/DACOSTAJA/AppData/Local/Android/Sdk"
cd mobile/android
./gradlew assembleDebug      # unsigned debug APK, for testing on your own device
./gradlew bundleRelease      # signed release .aab, for the Play Store (needs a signing key — see below)
```

Debug APK output: `mobile/android/app/build/outputs/apk/debug/app-debug.apk`.
Install it on a phone with USB debugging enabled via
`adb install app-debug.apk`, or just copy the file over and open it (you'll
need to allow "install from unknown sources" for a debug build).

> Note: this network's Gradle wrapper download hit a TLS/PKIX chain-building
> error from Java specifically (curl/Windows succeed fine, so it isn't a
> proxy/MITM problem — Java's `cacerts` truststore just doesn't complete the
> validation path for the resulting cert chain here). If `./gradlew` fails
> the same way, download the matching Gradle distribution zip directly via
> curl (`--ssl-no-revoke` if you also hit an OCSP/CRL timeout) and run its
> `bin/gradle` directly instead of the wrapper's bootstrap `gradlew`.

## What's still needed to actually publish

### Android — Google Play Store
1. **Google Play Console account** — $25 one-time registration fee, at
   https://play.google.com/console. This has to be done by you (or whoever
   owns the TimorMart business/brand) — I can't create accounts.
2. **App signing key** — generate a release keystore once:
   ```
   keytool -genkey -v -keystore timormart-release.keystore -alias timormart -keyalg RSA -keysize 2048 -validity 10000
   ```
   Keep this file and its password somewhere safe and backed up —
   **losing it means you can never update the app again** under the same
   listing; you'd have to publish as a new app. Google's "Play App Signing"
   (recommended, offered automatically during your first upload) manages the
   actual distribution key for you and only needs this as an "upload key",
   which is safer.
3. **Store listing assets**: app description, 2-8 screenshots per device
   type, a 512x512 icon (already generated, at `assets/icon.png`, scale up if
   Play Console wants it larger), a feature graphic (1024x500 banner).
4. **Privacy policy URL** — required by Play Console even for a simple app;
   TimorMart doesn't appear to have a published one yet.
5. **Content rating questionnaire** and **Data safety form** (what data the
   app collects — accounts, addresses, payment info via Stripe, etc.) —
   filled out in Play Console, not code.
6. Build `bundleRelease` (an `.aab`, Android's required upload format, not a
   raw `.apk`) and upload it to a new release in Play Console.

### iOS — Apple App Store
1. **Apple Developer Program membership** — $99/year, at
   https://developer.apple.com/programs/. Also has to be your own account.
2. **A Mac with Xcode** (or a cloud Mac CI service) to open `ios/App/App.xcworkspace`,
   set up signing (Xcode can auto-manage this once your Apple Developer
   account is added), and archive/upload the build.
3. **App Store Connect listing**: description, screenshots per device size,
   privacy policy URL, and Apple's "App Privacy" nutrition-label
   questionnaire (similar to Android's Data safety form).
4. Apple's review process is manual and typically takes 1-3 days; first
   submissions sometimes get rejected for missing privacy details or
   because a WebView-wrapped site needs to demonstrate enough native value
   — having the back-button/status-bar integration already in place here
   helps, but expect at least one review round-trip.

## Known limitations of this approach (documented, not urgent)

- **Requires internet connectivity** — there's no offline/cached mode; the
  app always loads the live site, same as a mobile browser would.
- **No native push notifications yet.** The site's existing in-app
  notification bell still works, but there's no way to notify a user who
  has the app closed. Adding this later means: wiring Firebase Cloud
  Messaging (Android) / APNs (iOS) via `@capacitor/push-notifications`,
  plus a Django-side endpoint to register device tokens per user and a
  place to actually trigger sends (e.g. alongside the existing order-status
  notification logic).
- **No native camera/file-picker polish** — file uploads (product photos,
  delivery proof) go through the browser's standard `<input type="file">`,
  which Android/iOS WebViews handle natively already (camera/gallery
  picker), so this mostly just works, but hasn't been explicitly tested
  end-to-end inside the wrapped app yet.
