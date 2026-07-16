#include <QApplication>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QCoreApplication>
#include <QDebug>
#include <QDir>
#include <QFileInfo>
#include <QStandardPaths>
#include <QStringList>

#include <utility>

#include <qtfluentwidgets.h>

#include "native_main_window.h"

namespace {

bool isBandoriResourceRoot(const QString& path) {
    const QDir root(path);
    return QFileInfo::exists(root.filePath(QStringLiteral("outfit.json")))
        && QFileInfo::exists(root.filePath(QStringLiteral("band.json")))
        && QFileInfo::exists(root.filePath(
            QStringLiteral("third_party/Live2D-v2-Lua/live2d_moc3_pet_embed.lua")));
}

QString discoverBandoriResourceRoot() {
    QStringList candidates;
    const QString environment = qEnvironmentVariable("BANDORI_PET_PROJECT_ROOT").trimmed();
    if (!environment.isEmpty()) {
        candidates.append(environment);
    }
    const QDir application(QCoreApplication::applicationDirPath());
    candidates.append(application.absolutePath());
    candidates.append(application.absoluteFilePath(QStringLiteral("../Resources")));
    candidates.append(application.absoluteFilePath(QStringLiteral("../share/bandoripet")));
    candidates.append(QDir::currentPath());
    for (const QString& candidate : std::as_const(candidates)) {
        const QString absolute = QDir(candidate).absolutePath();
        if (isBandoriResourceRoot(absolute)) {
            return absolute;
        }
    }
    return QDir::currentPath();
}

bool isPackagedResourceRoot(const QString& path) {
    return QFileInfo::exists(
        QDir(path).filePath(QStringLiteral(".bandoripet-native-package")));
}

}  // namespace

int main(int argc, char* argv[]) {
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("BandoriPet"));
    QApplication::setOrganizationName(QStringLiteral("BandoriPet"));
    QApplication::setQuitOnLastWindowClosed(false);

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
        QStringLiteral("path"));
    QCommandLineOption dataRoot(
        QStringLiteral("data-root"),
        QStringLiteral("Writable BandoriPet configuration and database directory"),
        QStringLiteral("path"));
    QCommandLineOption configPathOption(
        QStringLiteral("config"),
        QStringLiteral("Explicit config.json path; its directory becomes the default data root"),
        QStringLiteral("path"));
    QCommandLineOption userModels(
        QStringLiteral("user-models"),
        QStringLiteral("Writable user model directory"),
        QStringLiteral("path"));
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
         dataRoot,
         configPathOption,
         userModels});
    parser.process(app);

    Q_INIT_RESOURCE(resource);
    qfw::setTheme(qfw::Theme::Auto);

    const QString resolvedProjectRoot = parser.isSet(projectRoot)
        ? QDir(parser.value(projectRoot)).absolutePath()
        : discoverBandoriResourceRoot();
    QString resolvedDataRoot;
    if (parser.isSet(dataRoot)) {
        resolvedDataRoot = QDir(parser.value(dataRoot)).absolutePath();
    } else if (parser.isSet(configPathOption)) {
        resolvedDataRoot = QFileInfo(parser.value(configPathOption)).absolutePath();
    } else if (parser.isSet(projectRoot) || !isPackagedResourceRoot(resolvedProjectRoot)) {
        resolvedDataRoot = resolvedProjectRoot;
    } else {
        resolvedDataRoot =
            QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    }
    if (resolvedDataRoot.isEmpty() || !QDir().mkpath(resolvedDataRoot)) {
        qCritical("Could not create the BandoriPet data directory");
        return 2;
    }
    const QString configPath = parser.isSet(configPathOption)
        ? QFileInfo(parser.value(configPathOption)).absoluteFilePath()
        : QDir(resolvedDataRoot).filePath(QStringLiteral("config.json"));
    const QString resolvedUserModels = parser.isSet(userModels)
        ? QDir(parser.value(userModels)).absolutePath()
        : QDir(resolvedDataRoot).filePath(QStringLiteral("models"));
    if (!QDir().mkpath(resolvedUserModels)) {
        qCritical("Could not create the BandoriPet user-model directory");
        return 2;
    }
    bandori::PetLaunchSpec petSpec;
    petSpec.projectRoot = resolvedProjectRoot;
    petSpec.userModelsRoot = resolvedUserModels;
    petSpec.configPath = configPath;
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
        resolvedProjectRoot,
        resolvedUserModels,
        resolvedDataRoot,
        configPath);
    window.show();
    if (!petSpec.modelPath.isEmpty()) {
        window.startPet(petSpec);
    } else {
        window.startConfiguredPets();
    }
    return app.exec();
}
