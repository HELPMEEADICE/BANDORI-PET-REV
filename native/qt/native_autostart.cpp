#include "native_autostart.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <QStandardPaths>

#include <algorithm>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

namespace bandori {

namespace {

void setError(QString* error, const QString& message) {
    if (error != nullptr) {
        *error = message;
    }
}

QString normalizedPath(const QString& path) {
    return QDir::cleanPath(QFileInfo(path).absoluteFilePath());
}

#ifdef Q_OS_WIN

QString quoteWindowsArgument(const QString& argument) {
    if (!argument.isEmpty()
        && !argument.contains(QLatin1Char(' '))
        && !argument.contains(QLatin1Char('\t'))
        && !argument.contains(QLatin1Char('"'))) {
        return argument;
    }
    QString quoted = QStringLiteral("\"");
    qsizetype backslashes = 0;
    for (const QChar character : argument) {
        if (character == QLatin1Char('\\')) {
            ++backslashes;
            continue;
        }
        if (character == QLatin1Char('"')) {
            quoted += QString(backslashes * 2 + 1, QLatin1Char('\\'));
            quoted += character;
            backslashes = 0;
            continue;
        }
        quoted += QString(backslashes, QLatin1Char('\\'));
        quoted += character;
        backslashes = 0;
    }
    quoted += QString(backslashes * 2, QLatin1Char('\\'));
    quoted += QLatin1Char('"');
    return quoted;
}

QString windowsCommand(const QString& executable, const QStringList& arguments) {
    QStringList command {quoteWindowsArgument(QDir::toNativeSeparators(executable))};
    for (const QString& argument : arguments) {
        command.append(quoteWindowsArgument(QDir::toNativeSeparators(argument)));
    }
    return command.join(QLatin1Char(' '));
}

QString readWindowsRunValue(QString* error) {
    HKEY key = nullptr;
    const LONG opened = RegOpenKeyExW(
        HKEY_CURRENT_USER,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        0,
        KEY_QUERY_VALUE,
        &key);
    if (opened == ERROR_FILE_NOT_FOUND) {
        return {};
    }
    if (opened != ERROR_SUCCESS) {
        setError(error, QStringLiteral("Could not open the Windows user Run key (%1)").arg(opened));
        return {};
    }
    DWORD type = 0;
    DWORD bytes = 0;
    LONG result = RegQueryValueExW(
        key,
        L"BandoriPet",
        nullptr,
        &type,
        nullptr,
        &bytes);
    if (result == ERROR_FILE_NOT_FOUND) {
        RegCloseKey(key);
        return {};
    }
    if (result != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ)) {
        RegCloseKey(key);
        setError(error, QStringLiteral("Could not read the Windows auto-start value (%1)").arg(result));
        return {};
    }
    std::wstring buffer((bytes / sizeof(wchar_t)) + 1, L'\0');
    result = RegQueryValueExW(
        key,
        L"BandoriPet",
        nullptr,
        &type,
        reinterpret_cast<LPBYTE>(buffer.data()),
        &bytes);
    RegCloseKey(key);
    if (result != ERROR_SUCCESS) {
        setError(error, QStringLiteral("Could not read the Windows auto-start command (%1)").arg(result));
        return {};
    }
    const auto terminator = std::find(buffer.cbegin(), buffer.cend(), L'\0');
    buffer.resize(static_cast<std::size_t>(std::distance(buffer.cbegin(), terminator)));
    return QString::fromStdWString(buffer);
}

bool writeWindowsRunValue(bool enabled, const QString& command, QString* error) {
    HKEY key = nullptr;
    DWORD disposition = 0;
    const LONG opened = RegCreateKeyExW(
        HKEY_CURRENT_USER,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        0,
        nullptr,
        0,
        KEY_SET_VALUE,
        nullptr,
        &key,
        &disposition);
    Q_UNUSED(disposition);
    if (opened != ERROR_SUCCESS) {
        setError(error, QStringLiteral("Could not open the Windows user Run key (%1)").arg(opened));
        return false;
    }
    LONG result = ERROR_SUCCESS;
    if (enabled) {
        const std::wstring value = command.toStdWString();
        result = RegSetValueExW(
            key,
            L"BandoriPet",
            0,
            REG_SZ,
            reinterpret_cast<const BYTE*>(value.c_str()),
            static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t)));
    } else {
        result = RegDeleteValueW(key, L"BandoriPet");
        if (result == ERROR_FILE_NOT_FOUND) {
            result = ERROR_SUCCESS;
        }
    }
    RegCloseKey(key);
    if (result != ERROR_SUCCESS) {
        setError(error, QStringLiteral("Could not update Windows auto-start (%1)").arg(result));
        return false;
    }
    return true;
}

#elif defined(Q_OS_MACOS)

QString xmlEscaped(QString value) {
    return value.replace(QLatin1Char('&'), QStringLiteral("&amp;"))
        .replace(QLatin1Char('<'), QStringLiteral("&lt;"))
        .replace(QLatin1Char('>'), QStringLiteral("&gt;"))
        .replace(QLatin1Char('"'), QStringLiteral("&quot;"))
        .replace(QLatin1Char('\''), QStringLiteral("&apos;"));
}

QString macLaunchAgentPath() {
    return QDir::home().filePath(
        QStringLiteral("Library/LaunchAgents/io.github.helpeadice.bandoripet.plist"));
}

QByteArray macLaunchAgent(const QString& executable, const QStringList& arguments) {
    QStringList values {normalizedPath(executable)};
    values.append(arguments);
    QString programArguments;
    for (const QString& value : values) {
        programArguments += QStringLiteral("    <string>%1</string>\n").arg(xmlEscaped(value));
    }
    return QStringLiteral(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
        "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
        "<plist version=\"1.0\">\n"
        "<dict>\n"
        "  <key>Label</key>\n"
        "  <string>io.github.helpeadice.bandoripet</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n%1  </array>\n"
        "  <key>RunAtLoad</key>\n"
        "  <true/>\n"
        "</dict>\n"
        "</plist>\n")
        .arg(programArguments)
        .toUtf8();
}

#else

QString desktopQuoted(QString argument) {
    argument.replace(QLatin1Char('%'), QStringLiteral("%%"));
    argument.replace(QLatin1Char('\\'), QStringLiteral("\\\\"));
    argument.replace(QLatin1Char('"'), QStringLiteral("\\\""));
    argument.replace(QLatin1Char('`'), QStringLiteral("\\`"));
    argument.replace(QLatin1Char('$'), QStringLiteral("\\$"));
    return QStringLiteral("\"%1\"").arg(argument);
}

QString linuxAutoStartPath() {
    QString configRoot = QStandardPaths::writableLocation(QStandardPaths::ConfigLocation);
    if (configRoot.isEmpty()) {
        configRoot = QDir::home().filePath(QStringLiteral(".config"));
    }
    return QDir(configRoot).filePath(QStringLiteral("autostart/bandoripet.desktop"));
}

QByteArray linuxDesktopEntry(const QString& executable, const QStringList& arguments) {
    QStringList command {desktopQuoted(normalizedPath(executable))};
    for (const QString& argument : arguments) {
        command.append(desktopQuoted(argument));
    }
    return QStringLiteral(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=BandoriPet\n"
        "Comment=Native Bandori desktop pet\n"
        "Exec=%1\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n")
        .arg(command.join(QLatin1Char(' ')))
        .toUtf8();
}

#endif

bool writeAutoStartFile(const QString& path, const QByteArray& payload, QString* error) {
    const QFileInfo info(path);
    if (!QDir().mkpath(info.absolutePath())) {
        setError(error, QStringLiteral("Could not create auto-start directory: %1").arg(info.absolutePath()));
        return false;
    }
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly) || file.write(payload) != payload.size() || !file.commit()) {
        setError(error, QStringLiteral("Could not write auto-start file: %1").arg(path));
        return false;
    }
    return true;
}

}  // namespace

QStringList nativeAutoStartArguments(
    const QString& projectRoot,
    const QString& dataRoot,
    const QString& configPath,
    const QString& userModelsRoot) {
    return {
        QStringLiteral("--project-root"),
        normalizedPath(projectRoot),
        QStringLiteral("--data-root"),
        normalizedPath(dataRoot),
        QStringLiteral("--config"),
        normalizedPath(configPath),
        QStringLiteral("--user-models"),
        normalizedPath(userModelsRoot),
    };
}

bool nativeAutoStartEnabled(
    const QString& executable,
    const QStringList& arguments,
    QString* error) {
    setError(error, {});
#ifdef Q_OS_WIN
    const QString actual = readWindowsRunValue(error);
    return !actual.isEmpty() && actual == windowsCommand(normalizedPath(executable), arguments);
#elif defined(Q_OS_MACOS)
    QFile file(macLaunchAgentPath());
    return file.open(QIODevice::ReadOnly)
        && file.readAll() == macLaunchAgent(executable, arguments);
#else
    QFile file(linuxAutoStartPath());
    return file.open(QIODevice::ReadOnly)
        && file.readAll() == linuxDesktopEntry(executable, arguments);
#endif
}

bool setNativeAutoStartEnabled(
    bool enabled,
    const QString& executable,
    const QStringList& arguments,
    QString* error) {
    setError(error, {});
    if (enabled && !QFileInfo::exists(executable)) {
        setError(error, QStringLiteral("Native executable does not exist: %1").arg(executable));
        return false;
    }
#ifdef Q_OS_WIN
    return writeWindowsRunValue(
        enabled,
        windowsCommand(normalizedPath(executable), arguments),
        error);
#elif defined(Q_OS_MACOS)
    if (enabled) {
        return writeAutoStartFile(
            macLaunchAgentPath(), macLaunchAgent(executable, arguments), error);
    }
    if (QFile::remove(macLaunchAgentPath()) || !QFileInfo::exists(macLaunchAgentPath())) {
        return true;
    }
    setError(error, QStringLiteral("Could not remove auto-start file: %1").arg(macLaunchAgentPath()));
    return false;
#else
    if (enabled) {
        return writeAutoStartFile(
            linuxAutoStartPath(), linuxDesktopEntry(executable, arguments), error);
    }
    if (QFile::remove(linuxAutoStartPath()) || !QFileInfo::exists(linuxAutoStartPath())) {
        return true;
    }
    setError(error, QStringLiteral("Could not remove auto-start file: %1").arg(linuxAutoStartPath()));
    return false;
#endif
}

}  // namespace bandori
