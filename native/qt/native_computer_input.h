#pragma once

#include <QPoint>
#include <QString>

namespace bandori {

bool nativeComputerMouseAction(
    const QString& action,
    const QPoint& position,
    const QString& button,
    int delta,
    QString* error = nullptr);

bool nativeComputerTypeText(const QString& text, QString* error = nullptr);

bool nativeComputerPressKeys(const QString& keys, QString* error = nullptr);

QString nativeComputerInputBackend();

}  // namespace bandori
