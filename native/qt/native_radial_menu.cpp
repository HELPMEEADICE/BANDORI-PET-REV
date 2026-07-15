#include "native_radial_menu.h"

#include <QFocusEvent>
#include <QFontMetrics>
#include <QGuiApplication>
#include <QHideEvent>
#include <QKeyEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QRadialGradient>
#include <QRegion>
#include <QScreen>
#include <QEasingCurve>
#include <QVariantAnimation>

#include <algorithm>
#include <cmath>

namespace bandori {

namespace {
constexpr int kMenuExtent = 380;
constexpr double kItemRadius = 38.0;
constexpr double kOrbitRadius = 110.0;
constexpr double kCenterRadius = 32.0;
constexpr double kPi = 3.14159265358979323846;
}

NativeRadialMenu::NativeRadialMenu(QWidget* parent)
    : QWidget(parent) {
    Qt::WindowFlags flags = Qt::Popup | Qt::FramelessWindowHint
        | Qt::WindowStaysOnTopHint | Qt::NoDropShadowWindowHint;
#ifdef Q_OS_LINUX
    flags |= Qt::X11BypassWindowManagerHint;
#endif
    setWindowFlags(flags);
    setAttribute(Qt::WA_TranslucentBackground, true);
    setAttribute(Qt::WA_NoSystemBackground, true);
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
    resize(kMenuExtent, kMenuExtent);
    releaseGuardTimer_.setInterval(20);
    connect(&releaseGuardTimer_, &QTimer::timeout, this, [this]() {
        if (QGuiApplication::mouseButtons() == Qt::NoButton) {
            ignoreReleaseUntilButtonsUp_ = false;
            releaseGuardTimer_.stop();
        }
    });
    items_ = {
        {QStringLiteral("chat"), {}, QStringLiteral("💬"), QColor(138, 43, 226), true},
        {QStringLiteral("costume"), {}, QStringLiteral("👗"), QColor(220, 50, 120), true},
        {QStringLiteral("motion"), {}, QStringLiteral("🎬"), QColor(30, 144, 255), true},
        {QStringLiteral("pixel"), {}, QStringLiteral("2D"), QColor(124, 92, 210), false},
    };
    updateLabels();
}

void NativeRadialMenu::setLocked(bool locked) {
    if (locked_ == locked) {
        return;
    }
    locked_ = locked;
    update();
}

void NativeRadialMenu::setLanguage(const QString& language) {
    if (language_ == language) {
        return;
    }
    language_ = language;
    updateLabels();
    update();
}

void NativeRadialMenu::setPixelAvailable(bool available) {
    if (items_.size() >= 4) {
        items_[3].enabled = available;
    }
    update();
}

void NativeRadialMenu::showAt(const QPoint& globalCenter) {
    if (animation_ != nullptr) {
        animation_->stop();
        animation_->deleteLater();
        animation_ = nullptr;
    }
    QScreen* screen = QGuiApplication::screenAt(globalCenter);
    if (screen == nullptr) {
        screen = QGuiApplication::primaryScreen();
    }
    QRect geometry(
        globalCenter.x() - kMenuExtent / 2,
        globalCenter.y() - kMenuExtent / 2,
        kMenuExtent,
        kMenuExtent);
    if (screen != nullptr) {
        const QRect available = screen->availableGeometry();
        geometry.moveLeft(std::clamp(
            geometry.left(),
            available.left(),
            std::max(available.left(), available.right() - geometry.width() + 1)));
        geometry.moveTop(std::clamp(
            geometry.top(),
            available.top(),
            std::max(available.top(), available.bottom() - geometry.height() + 1)));
    }
    setGeometry(geometry);
    reveal_ = 0.0;
    closing_ = false;
    hoverIndex_ = -1;
    centerHover_ = false;
    ignoreReleaseUntilButtonsUp_ = QGuiApplication::mouseButtons() != Qt::NoButton;
    if (ignoreReleaseUntilButtonsUp_) {
        releaseGuardTimer_.start();
    }
    updateInteractiveMask();
    const bool newlyOpened = !open_;
    open_ = true;
    show();
    raise();
    activateWindow();
    setFocus(Qt::PopupFocusReason);
    startRevealAnimation(1.0, 180, false);
    if (newlyOpened) {
        emit opened();
    }
}

void NativeRadialMenu::dismiss() {
    if (!open_ || closing_) {
        return;
    }
    startRevealAnimation(0.0, 120, true);
}

void NativeRadialMenu::paintEvent(QPaintEvent*) {
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    const double opacity = std::clamp(reveal_, 0.0, 1.0);
    for (int index = 0; index < items_.size(); ++index) {
        const Item& item = items_.at(index);
        const QPointF center = centerForItem(index);
        QColor color = item.enabled ? item.color : QColor(112, 112, 118);
        if (item.enabled && hoverIndex_ == index) {
            color = color.lighter(128);
        }
        painter.save();
        painter.setOpacity(opacity);
        painter.setPen(Qt::NoPen);
        painter.setBrush(QColor(0, 0, 0, item.enabled ? 42 : 24));
        painter.drawEllipse(center + QPointF(0.0, 2.0), kItemRadius, kItemRadius);
        QRadialGradient gradient(
            center.x(), center.y() - kItemRadius * 0.3, kItemRadius * 1.25);
        gradient.setColorAt(0.0, color.lighter(158));
        gradient.setColorAt(0.64, color);
        gradient.setColorAt(1.0, color.darker(118));
        painter.setBrush(gradient);
        painter.drawEllipse(center, kItemRadius, kItemRadius);
        painter.setBrush(Qt::NoBrush);
        painter.setPen(QPen(QColor(255, 255, 255, item.enabled ? 96 : 48), 1.4));
        painter.drawEllipse(center, kItemRadius - 1.0, kItemRadius - 1.0);

        QFont glyphFont = painter.font();
        glyphFont.setBold(true);
        glyphFont.setPointSize(item.glyph == QStringLiteral("2D") ? 12 : 20);
        painter.setFont(glyphFont);
        painter.setPen(QColor(255, 255, 255, item.enabled ? 240 : 160));
        painter.drawText(
            QRectF(center.x() - 30.0, center.y() - 29.0, 60.0, 35.0),
            Qt::AlignCenter,
            item.glyph);

        QFont labelFont = painter.font();
        labelFont.setPointSize(8);
        labelFont.setBold(true);
        painter.setFont(labelFont);
        const QFontMetrics metrics(labelFont);
        const QString label = metrics.elidedText(item.label, Qt::ElideRight, 60);
        painter.drawText(
            QRectF(center.x() - 32.0, center.y() + 9.0, 64.0, 22.0),
            Qt::AlignCenter,
            label);
        painter.restore();
    }

    const QPointF center(width() * 0.5, height() * 0.5);
    QColor centerColor = centerHover_ ? QColor(68, 68, 74) : QColor(42, 42, 47);
    painter.setOpacity(opacity);
    QRadialGradient centerGradient(
        center.x(), center.y() - kCenterRadius * 0.2, kCenterRadius * 1.25);
    centerGradient.setColorAt(0.0, centerColor.lighter(145));
    centerGradient.setColorAt(0.72, centerColor);
    centerGradient.setColorAt(1.0, centerColor.darker(135));
    painter.setPen(QPen(QColor(255, 255, 255, 78), 1.5));
    painter.setBrush(centerGradient);
    painter.drawEllipse(center, kCenterRadius, kCenterRadius);
    QFont lockFont = painter.font();
    lockFont.setPointSize(18);
    painter.setFont(lockFont);
    painter.setPen(QColor(255, 255, 255, 220));
    painter.drawText(
        QRectF(
            center.x() - kCenterRadius,
            center.y() - kCenterRadius,
            kCenterRadius * 2.0,
            kCenterRadius * 2.0),
        Qt::AlignCenter,
        locked_ ? QStringLiteral("🔒") : QStringLiteral("🔓"));
    painter.setOpacity(1.0);
}

void NativeRadialMenu::mouseMoveEvent(QMouseEvent* event) {
    const int nextHover = itemAt(event->position());
    const bool nextCenterHover = centerContains(event->position());
    if (nextHover != hoverIndex_ || nextCenterHover != centerHover_) {
        hoverIndex_ = nextHover;
        centerHover_ = nextCenterHover;
        update();
    }
    QWidget::mouseMoveEvent(event);
}

void NativeRadialMenu::mouseReleaseEvent(QMouseEvent* event) {
    if (ignoreReleaseUntilButtonsUp_) {
        if (QGuiApplication::mouseButtons() == Qt::NoButton) {
            ignoreReleaseUntilButtonsUp_ = false;
            releaseGuardTimer_.stop();
        }
        event->accept();
        return;
    }
    if (event->button() != Qt::LeftButton) {
        dismiss();
        event->accept();
        return;
    }
    if (centerContains(event->position())) {
        locked_ = !locked_;
        emit lockToggled(locked_);
        update();
        event->accept();
        return;
    }
    const int index = itemAt(event->position());
    if (index >= 0 && items_.at(index).enabled) {
        emit actionTriggered(items_.at(index).action);
        dismiss();
        event->accept();
        return;
    }
    dismiss();
    event->accept();
}

void NativeRadialMenu::leaveEvent(QEvent* event) {
    hoverIndex_ = -1;
    centerHover_ = false;
    update();
    QWidget::leaveEvent(event);
}

void NativeRadialMenu::keyPressEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_Escape) {
        dismiss();
        event->accept();
        return;
    }
    QWidget::keyPressEvent(event);
}

void NativeRadialMenu::focusOutEvent(QFocusEvent* event) {
    QWidget::focusOutEvent(event);
    dismiss();
}

void NativeRadialMenu::hideEvent(QHideEvent* event) {
    QWidget::hideEvent(event);
    if (open_) {
        releaseGuardTimer_.stop();
        ignoreReleaseUntilButtonsUp_ = false;
        open_ = false;
        closing_ = false;
        emit closed();
    }
}

QPointF NativeRadialMenu::centerForItem(int index) const {
    const qsizetype itemCount = items_.isEmpty() ? 1 : items_.size();
    const double angle = -kPi / 2.0
        + 2.0 * kPi * static_cast<double>(index) / static_cast<double>(itemCount);
    const QPointF center(width() * 0.5, height() * 0.5);
    return center
        + QPointF(
            std::cos(angle) * kOrbitRadius * reveal_,
            std::sin(angle) * kOrbitRadius * reveal_);
}

int NativeRadialMenu::itemAt(const QPointF& position) const {
    for (int index = 0; index < items_.size(); ++index) {
        const QPointF delta = position - centerForItem(index);
        if (delta.x() * delta.x() + delta.y() * delta.y() <= kItemRadius * kItemRadius) {
            return index;
        }
    }
    return -1;
}

bool NativeRadialMenu::centerContains(const QPointF& position) const {
    const QPointF center(width() * 0.5, height() * 0.5);
    const QPointF delta = position - center;
    return delta.x() * delta.x() + delta.y() * delta.y() <= kCenterRadius * kCenterRadius;
}

void NativeRadialMenu::updateLabels() {
    const bool chinese = language_.trimmed().toLower().startsWith(QStringLiteral("zh"));
    if (items_.size() < 4) {
        return;
    }
    items_[0].label = chinese ? QStringLiteral("聊天") : QStringLiteral("Chat");
    items_[1].label = chinese ? QStringLiteral("换装") : QStringLiteral("Outfit");
    items_[2].label = chinese ? QStringLiteral("动作") : QStringLiteral("Motion");
    items_[3].label = chinese ? QStringLiteral("像素") : QStringLiteral("Pixel");
}

void NativeRadialMenu::updateInteractiveMask() {
    QRegion region(
        QRect(
            width() / 2 - static_cast<int>(kCenterRadius),
            height() / 2 - static_cast<int>(kCenterRadius),
            static_cast<int>(kCenterRadius * 2.0),
            static_cast<int>(kCenterRadius * 2.0)),
        QRegion::Ellipse);
    for (int index = 0; index < items_.size(); ++index) {
        const QPointF center = centerForItem(index);
        const QRect rectangle(
            qRound(center.x() - kItemRadius),
            qRound(center.y() - kItemRadius),
            qRound(kItemRadius * 2.0),
            qRound(kItemRadius * 2.0));
        region = region.united(QRegion(rectangle, QRegion::Ellipse));
    }
    setMask(region);
}

void NativeRadialMenu::startRevealAnimation(double endValue, int duration, bool closing) {
    if (animation_ != nullptr) {
        animation_->stop();
        animation_->deleteLater();
    }
    closing_ = closing;
    auto* animation = new QVariantAnimation(this);
    animation_ = animation;
    animation->setStartValue(reveal_);
    animation->setEndValue(endValue);
    animation->setDuration(duration);
    animation->setEasingCurve(closing ? QEasingCurve::InBack : QEasingCurve::OutBack);
    connect(animation, &QVariantAnimation::valueChanged, this, [this](const QVariant& value) {
        reveal_ = std::clamp(value.toDouble(), 0.0, 1.08);
        updateInteractiveMask();
        update();
    });
    connect(animation, &QVariantAnimation::finished, this, [this, animation, closing]() {
        if (animation_ != animation) {
            animation->deleteLater();
            return;
        }
        animation_ = nullptr;
        animation->deleteLater();
        reveal_ = closing ? 0.0 : 1.0;
        closing_ = false;
        updateInteractiveMask();
        update();
        if (closing) {
            hide();
        }
    });
    animation->start();
}

} // namespace bandori
