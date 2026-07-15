#include <QApplication>
#include <QDir>
#include <QVBoxLayout>
#include <QWidget>

#include <bandori_qt_bridge/src/backend.cxxqt.h>
#include <qtfluentwidgets.h>

int main(int argc, char* argv[]) {
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("BandoriPet"));
    QApplication::setOrganizationName(QStringLiteral("BandoriPet"));

    Q_INIT_RESOURCE(resource);
    qfw::setTheme(qfw::Theme::Auto);

    bandori::Backend backend;
    backend.loadConfig(QDir::current().filePath(QStringLiteral("config.json")));

    qfw::FluentWidget window;
    window.setWindowTitle(QStringLiteral("BandoriPet Rust migration"));
    window.resize(720, 420);

    auto* page = new QWidget(&window);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(40, 52, 40, 40);
    layout->setSpacing(16);

    auto* title = new qfw::TitleLabel(QStringLiteral("BandoriPet Rust + Qt"), page);
    auto* summary = new qfw::BodyLabel(backend.status(), page);
    auto* reload = new qfw::PrimaryPushButton(QStringLiteral("Reload configuration"), page);

    layout->addWidget(title);
    layout->addWidget(summary);
    layout->addWidget(reload, 0, Qt::AlignLeft);
    layout->addStretch(1);

    QObject::connect(reload, &QPushButton::clicked, page, [&backend, summary]() {
        backend.loadConfig(QDir::current().filePath(QStringLiteral("config.json")));
        summary->setText(backend.status());
    });

    window.setContentWidget(page);
    window.show();
    return app.exec();
}
