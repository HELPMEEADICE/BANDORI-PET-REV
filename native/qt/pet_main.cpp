#include "live2d_gl_widget.h"

#include <QApplication>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QDir>
#include <QStandardPaths>

#include <algorithm>

int main(int argc, char* argv[]) {
    bandori::Live2dGlWidget::configureDefaultSurfaceFormat(true);
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("BandoriPetRenderer"));
    QApplication::setOrganizationName(QStringLiteral("BandoriPet"));
    QApplication::setQuitOnLastWindowClosed(true);

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Isolated Rust + LuaJIT Live2D pet renderer"));
    parser.addHelpOption();
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
    QCommandLineOption model(
        QStringLiteral("model"),
        QStringLiteral("Model manifest path"),
        QStringLiteral("path"));
    QCommandLineOption format(
        QStringLiteral("format"),
        QStringLiteral("Model format: moc or moc3"),
        QStringLiteral("format"),
        QStringLiteral("moc3"));
    QCommandLineOption width(
        QStringLiteral("width"), QStringLiteral("Pet width"), QStringLiteral("pixels"), QStringLiteral("400"));
    QCommandLineOption height(
        QStringLiteral("height"), QStringLiteral("Pet height"), QStringLiteral("pixels"), QStringLiteral("650"));
    parser.addOptions({projectRoot, userModels, model, format, width, height});
    parser.process(app);

    if (!parser.isSet(model)) {
        parser.showHelp(2);
    }
    const auto modelFormat = parser.value(format).compare(QStringLiteral("moc"), Qt::CaseInsensitive) == 0
        ? bandori::Live2dGlWidget::ModelFormat::Moc
        : bandori::Live2dGlWidget::ModelFormat::Moc3;
    bandori::Live2dGlWidget widget(
        parser.value(projectRoot),
        parser.value(userModels),
        parser.value(model),
        modelFormat);
    widget.setWindowFlags(Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint);
    widget.setAttribute(Qt::WA_TranslucentBackground, true);
    widget.resize(std::max(parser.value(width).toInt(), 1), std::max(parser.value(height).toInt(), 1));
    widget.show();
    return app.exec();
}
