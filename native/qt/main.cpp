#include <QApplication>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QDir>
#include <QStandardPaths>

#include <qtfluentwidgets.h>

#include "native_main_window.h"

int main(int argc, char* argv[]) {
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("BandoriPet"));
    QApplication::setOrganizationName(QStringLiteral("BandoriPet"));

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("BandoriPet Rust + Qt migration shell"));
    parser.addHelpOption();
    QCommandLineOption petModel(
        QStringLiteral("pet-model"),
        QStringLiteral("Launch the isolated Rust pet renderer with this model manifest"),
        QStringLiteral("path"));
    QCommandLineOption petFormat(
        QStringLiteral("pet-format"),
        QStringLiteral("Pet model format: moc or moc3"),
        QStringLiteral("format"),
        QStringLiteral("moc3"));
    QCommandLineOption petCharacter(
        QStringLiteral("pet-character"),
        QStringLiteral("Character identifier used for IPC registration"),
        QStringLiteral("id"));
    QCommandLineOption petLanguage(
        QStringLiteral("pet-language"),
        QStringLiteral("Language used by native pet controls"),
        QStringLiteral("locale"));
    QCommandLineOption petFps(
        QStringLiteral("pet-fps"),
        QStringLiteral("Pet render frame rate"),
        QStringLiteral("fps"),
        QStringLiteral("120"));
    QCommandLineOption petX(
        QStringLiteral("pet-x"),
        QStringLiteral("Initial pet X position"),
        QStringLiteral("x"),
        QStringLiteral("-1"));
    QCommandLineOption petY(
        QStringLiteral("pet-y"),
        QStringLiteral("Initial pet Y position"),
        QStringLiteral("y"),
        QStringLiteral("-1"));
    QCommandLineOption petOpacity(
        QStringLiteral("pet-opacity"),
        QStringLiteral("Pet window opacity"),
        QStringLiteral("opacity"),
        QStringLiteral("1.0"));
    QCommandLineOption petLipSyncMaxOpen(
        QStringLiteral("pet-lip-sync-max-open"),
        QStringLiteral("Maximum mouth-open parameter used by pet lip sync"),
        QStringLiteral("value"),
        QStringLiteral("0.55"));
    QCommandLineOption petHitAlphaThreshold(
        QStringLiteral("pet-hit-alpha-threshold"),
        QStringLiteral("Alpha threshold used for pet input passthrough"),
        QStringLiteral("alpha"),
        QStringLiteral("8"));
    QCommandLineOption petClickMotionActions(
        QStringLiteral("pet-click-motion-actions"),
        QStringLiteral("Per-region click motion feedback JSON"),
        QStringLiteral("json"),
        QStringLiteral("{}"));
    QCommandLineOption petPokeMotion(
        QStringLiteral("pet-poke-motion"),
        QStringLiteral("Motion used for user poke feedback"),
        QStringLiteral("motion"));
    QCommandLineOption petPokeExpression(
        QStringLiteral("pet-poke-expression"),
        QStringLiteral("Expression used for user poke feedback"),
        QStringLiteral("expression"));
    QCommandLineOption petDragLocked(
        QStringLiteral("pet-drag-locked"),
        QStringLiteral("Whether direct pet dragging is locked"));
    QCommandLineOption petMoveAllRolesTogether(
        QStringLiteral("pet-move-all-roles-together"),
        QStringLiteral("Mirror drag sessions across pet processes"));
    QCommandLineOption petDisableHeadTracking(
        QStringLiteral("pet-disable-head-tracking"),
        QStringLiteral("Disable global cursor tracking for the pet"));
    QCommandLineOption petMutualGaze(
        QStringLiteral("pet-mutual-gaze"),
        QStringLiteral("Look toward the nearest active pet process"));
    QCommandLineOption projectRoot(
        QStringLiteral("project-root"),
        QStringLiteral("BandoriPet installation root"),
        QStringLiteral("path"),
        QDir::currentPath());
    QCommandLineOption userModels(
        QStringLiteral("user-models"),
        QStringLiteral("Writable user model directory"),
        QStringLiteral("path"),
        QStandardPaths::writableLocation(QStandardPaths::AppDataLocation) + QStringLiteral("/models"));
    parser.addOptions(
        {petModel,
         petFormat,
         petCharacter,
         petLanguage,
         petX,
         petY,
         petFps,
         petOpacity,
         petLipSyncMaxOpen,
         petHitAlphaThreshold,
         petClickMotionActions,
         petPokeMotion,
         petPokeExpression,
         petDragLocked,
         petMoveAllRolesTogether,
         petDisableHeadTracking,
         petMutualGaze,
         projectRoot,
         userModels});
    parser.process(app);

    Q_INIT_RESOURCE(resource);
    qfw::setTheme(qfw::Theme::Auto);

    const QString configPath =
        QDir(parser.value(projectRoot)).filePath(QStringLiteral("config.json"));
    bandori::PetLaunchSpec petSpec;
    petSpec.projectRoot = parser.value(projectRoot);
    petSpec.userModelsRoot = parser.value(userModels);
    petSpec.modelPath = parser.value(petModel);
    petSpec.character = parser.value(petCharacter);
    petSpec.language = parser.value(petLanguage);
    petSpec.format = parser.value(petFormat);
    petSpec.x = parser.value(petX).toInt();
    petSpec.y = parser.value(petY).toInt();
    petSpec.fps = parser.value(petFps).toInt();
    petSpec.opacity = parser.value(petOpacity).toDouble();
    petSpec.lipSyncMaxOpen = parser.value(petLipSyncMaxOpen).toDouble();
    petSpec.hitAlphaThreshold = parser.value(petHitAlphaThreshold).toInt();
    petSpec.clickMotionActions = parser.value(petClickMotionActions);
    petSpec.pokeMotion = parser.value(petPokeMotion);
    petSpec.pokeExpression = parser.value(petPokeExpression);
    petSpec.dragLocked = parser.isSet(petDragLocked);
    petSpec.moveAllRolesTogether = parser.isSet(petMoveAllRolesTogether);
    petSpec.headTrackingEnabled = !parser.isSet(petDisableHeadTracking);
    petSpec.mutualGazeEnabled = parser.isSet(petMutualGaze);
    bandori::NativeMainWindow window(
        parser.value(projectRoot),
        parser.value(userModels),
        configPath);
    window.show();
    if (!petSpec.modelPath.isEmpty()) {
        window.startPet(petSpec);
    } else {
        window.startConfiguredPet();
    }
    return app.exec();
}
