#pragma once

#include <QColor>
#include <QPointF>
#include <QString>
#include <QTimer>
#include <QVector>
#include <QWidget>

class QFocusEvent;
class QHideEvent;
class QKeyEvent;
class QMouseEvent;
class QPaintEvent;
class QVariantAnimation;

namespace bandori {

class NativeRadialMenu final : public QWidget {
    Q_OBJECT

public:
    explicit NativeRadialMenu(QWidget* parent = nullptr);

    void setLocked(bool locked);
    void setLanguage(const QString& language);
    void setPixelAvailable(bool available);
    void showAt(const QPoint& globalCenter);
    void dismiss();

signals:
    void actionTriggered(const QString& action);
    void lockToggled(bool locked);
    void opened();
    void closed();

protected:
    void paintEvent(QPaintEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void leaveEvent(QEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;
    void focusOutEvent(QFocusEvent* event) override;
    void hideEvent(QHideEvent* event) override;

private:
    struct Item {
        QString action;
        QString label;
        QString glyph;
        QColor color;
        bool enabled = true;
    };

    QPointF centerForItem(int index) const;
    int itemAt(const QPointF& position) const;
    bool centerContains(const QPointF& position) const;
    void updateLabels();
    void updateInteractiveMask();
    void startRevealAnimation(double endValue, int duration, bool closing);

    QVector<Item> items_;
    QVariantAnimation* animation_ = nullptr;
    QString language_;
    double reveal_ = 0.0;
    int hoverIndex_ = -1;
    bool centerHover_ = false;
    bool locked_ = false;
    bool open_ = false;
    bool closing_ = false;
    bool ignoreReleaseUntilButtonsUp_ = false;
    QTimer releaseGuardTimer_;
};

} // namespace bandori
