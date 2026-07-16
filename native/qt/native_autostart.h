#pragma once

#include <QString>
#include <QStringList>

namespace bandori {

QStringList nativeAutoStartArguments(
    const QString& projectRoot,
    const QString& dataRoot,
    const QString& configPath,
    const QString& userModelsRoot);

bool nativeAutoStartEnabled(
    const QString& executable,
    const QStringList& arguments,
    QString* error = nullptr);

bool setNativeAutoStartEnabled(
    bool enabled,
    const QString& executable,
    const QStringList& arguments,
    QString* error = nullptr);

}  // namespace bandori
