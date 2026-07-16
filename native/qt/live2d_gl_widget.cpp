#include "live2d_gl_widget.h"

#include <QByteArray>
#include <QCursor>
#include <QDebug>
#include <QEnterEvent>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QHideEvent>
#include <QImageReader>
#include <QJsonDocument>
#include <QMouseEvent>
#include <QOpenGLContext>
#include <QOpenGLExtraFunctions>
#include <QOpenGLFramebufferObject>
#include <QOpenGLFramebufferObjectFormat>
#include <QOpenGLFunctions>
#include <QSurfaceFormat>
#include <QPainter>
#include <QRandomGenerator>
#include <QScreen>
#include <QShowEvent>
#include <QWindow>

#include <algorithm>
#include <cmath>
#include <iterator>
#include <utility>

#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#endif

namespace bandori {

namespace {
constexpr int kAlphaHitIntervalMsec = 16;
constexpr int kAlphaHitGraceMsec = 80;
constexpr int kAlphaHitGraceDistance = 12;
constexpr int kDragThresholdSquared = 16;
constexpr int kPixelFrameHoldBeats = 3;
constexpr int kMaximumPixelFramesFileBytes = 1024 * 1024;
constexpr qint64 kMaximumPixelSheetFileBytes = 32LL * 1024 * 1024;
constexpr qint64 kMaximumPixelSheetPixels = 100'000'000;
}

void Live2dGlWidget::configureDefaultSurfaceFormat(bool vsync) {
    QSurfaceFormat format = QSurfaceFormat::defaultFormat();
    format.setAlphaBufferSize(8);
    format.setSamples(0);
    format.setDepthBufferSize(0);
    format.setStencilBufferSize(8);
    format.setSwapInterval(vsync ? 1 : 0);
    format.setVersion(2, 1);
    format.setRenderableType(QSurfaceFormat::OpenGL);
    format.setProfile(QSurfaceFormat::CompatibilityProfile);
    QSurfaceFormat::setDefaultFormat(format);
}

Live2dGlWidget::Live2dGlWidget(
    QString projectRoot,
    QString userModelsRoot,
    QString modelPath,
    ModelFormat format,
    RenderMode renderMode,
    QWidget* parent)
    : QOpenGLWidget(parent),
      projectRoot_(std::move(projectRoot)),
      userModelsRoot_(std::move(userModelsRoot)),
      modelPath_(std::move(modelPath)),
      format_(format),
      renderMode_(renderMode) {
    setAttribute(Qt::WA_TranslucentBackground, true);
    setAttribute(Qt::WA_NoSystemBackground, true);
    setAttribute(Qt::WA_OpaquePaintEvent, false);
    setAutoFillBackground(false);
    setMouseTracking(true);

    renderTimer_.setTimerType(Qt::PreciseTimer);
    connect(&renderTimer_, &QTimer::timeout, this, QOverload<>::of(&Live2dGlWidget::update));
    alphaHitTimer_.setTimerType(Qt::PreciseTimer);
    alphaHitTimer_.setInterval(kAlphaHitIntervalMsec);
    connect(&alphaHitTimer_, &QTimer::timeout, this, &Live2dGlWidget::requestAlphaSample);
    defaultStateTimer_.setTimerType(Qt::CoarseTimer);
    defaultStateTimer_.setInterval(500);
    connect(
        &defaultStateTimer_,
        &QTimer::timeout,
        this,
        &Live2dGlWidget::restoreDefaultMotionIfFinished);
    pixelAnimationTimer_.setTimerType(Qt::CoarseTimer);
    connect(
        &pixelAnimationTimer_,
        &QTimer::timeout,
        this,
        &Live2dGlWidget::advancePixelFrame);
    pixelWanderTimer_.setTimerType(Qt::PreciseTimer);
    pixelWanderTimer_.setInterval(33);
    connect(
        &pixelWanderTimer_,
        &QTimer::timeout,
        this,
        &Live2dGlWidget::stepPixelWander);
    setFramesPerSecond(120);
    alphaHitTimer_.start();
}

void Live2dGlWidget::setHitAlphaThreshold(int threshold) {
    hitAlphaThreshold_ = std::clamp(threshold, 0, 255);
}

Live2dGlWidget::~Live2dGlWidget() {
    disposeRuntime();
}

void Live2dGlWidget::setFramesPerSecond(int fps) {
    fps = std::clamp(fps, 10, 240);
    renderTimer_.setInterval(std::max(1, qRound(1000.0 / fps)));
    if (isVisible() && !pixelMode()) {
        renderTimer_.start();
    }
}

void Live2dGlWidget::setRenderQuality(const QString& quality) {
    if (host_ != nullptr) {
        qWarning() << "Live2D render quality requires recreating the renderer";
        return;
    }
    const bool performance =
        quality.trimmed().compare(QStringLiteral("performance"), Qt::CaseInsensitive) == 0;
    textureQuality_ = performance ? 0U : 1U;
    ssaaScale_ = performance ? 1 : 2;
}

void Live2dGlWidget::setDragLocked(bool locked) {
    dragLocked_ = locked;
    if (!pixelMode()) {
        return;
    }
    if (locked) {
        pixelWanderTimer_.stop();
        setPixelAnimation(QStringLiteral("idle"));
    } else if (isVisible()) {
        choosePixelWanderTarget();
        pixelWanderTimer_.start();
    }
}

bool Live2dGlWidget::dragLocked() const {
    return dragLocked_;
}

void Live2dGlWidget::setHeadTrackingEnabled(bool enabled) {
    headTrackingEnabled_ = enabled;
    gazeWasApplied_ = false;
    update();
}

void Live2dGlWidget::setGazeTargetGlobal(const QPoint& globalPosition) {
    gazeTargetGlobal_ = globalPosition;
    gazeWasApplied_ = false;
    update();
}

void Live2dGlWidget::clearGazeTarget() {
    gazeTargetGlobal_.reset();
    gazeWasApplied_ = false;
    update();
}

void Live2dGlWidget::setLipSyncMaxOpen(double value) {
    lipSyncMaxOpen_ = std::clamp(value, 0.0, 1.0);
    lipSyncTarget_ = std::clamp(lipSyncTarget_, 0.0, lipSyncMaxOpen_);
}

void Live2dGlWidget::setLipSyncPose(double level, double form) {
    if (pixelMode()) {
        return;
    }
    lipSyncTarget_ = std::clamp(level, 0.0, lipSyncMaxOpen_);
    lipSyncFormTarget_ = std::clamp(form, -1.0, 1.0);
    lipSyncLastMsec_ = frameClock_.isValid() ? frameClock_.elapsed() : 0;
    update();
}

bool Live2dGlWidget::loadPixelSprite(
    const QString& imagePath,
    const QString& framesPath) {
    const QFileInfo framesInfo(framesPath);
    if (!framesInfo.isFile() || framesInfo.size() <= 0
        || framesInfo.size() > kMaximumPixelFramesFileBytes) {
        return false;
    }
    QFile framesFile(framesPath);
    if (!framesFile.open(QIODevice::ReadOnly)) {
        return false;
    }
    QJsonParseError parseError;
    const QJsonDocument document =
        QJsonDocument::fromJson(framesFile.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        return false;
    }
    const QJsonObject root = document.object();
    const QJsonObject sheet = root.value(QStringLiteral("spriteSheet")).toObject();
    const QJsonObject animations = root.value(QStringLiteral("animations")).toObject();
    const int columns = sheet.value(QStringLiteral("totalCols")).toInt();
    const int rows = sheet.value(QStringLiteral("totalRows")).toInt();
    if (columns <= 0 || columns > 256 || rows <= 0 || rows > 256
        || animations.isEmpty() || animations.size() > 256) {
        return false;
    }
    const QFileInfo imageInfo(imagePath);
    if (!imageInfo.isFile() || imageInfo.size() <= 0
        || imageInfo.size() > kMaximumPixelSheetFileBytes) {
        return false;
    }
    QImageReader reader(imagePath);
    reader.setAutoTransform(false);
    const QSize imageSize = reader.size();
    if (!imageSize.isValid() || imageSize.width() < columns || imageSize.height() < rows
        || imageSize.width() % columns != 0 || imageSize.height() % rows != 0
        || static_cast<qint64>(imageSize.width()) * imageSize.height()
            > kMaximumPixelSheetPixels) {
        return false;
    }
    const int frameWidth = imageSize.width() / columns;
    const int frameHeight = imageSize.height() / rows;
    const int declaredFrameWidth = sheet.value(QStringLiteral("frameWidth")).toInt(frameWidth);
    const int declaredFrameHeight =
        sheet.value(QStringLiteral("frameHeight")).toInt(frameHeight);
    if (frameWidth != declaredFrameWidth || frameHeight != declaredFrameHeight) {
        return false;
    }
    QImage image = reader.read();
    if (image.isNull() || image.size() != imageSize) {
        return false;
    }
    pixelSheetImage_ = image.convertToFormat(QImage::Format_ARGB32);
    pixelSheet_ = QPixmap::fromImage(pixelSheetImage_);
    if (pixelSheet_.isNull()) {
        pixelSheetImage_ = {};
        return false;
    }
    pixelAnimations_ = animations;
    pixelTotalColumns_ = columns;
    pixelTotalRows_ = rows;
    pixelFrameSize_ = {
        frameWidth,
        frameHeight,
    };
    pixelFrameIndex_ = 0;
    setPixelAnimation(QStringLiteral("idle"));
    return true;
}

bool Live2dGlWidget::setPixelMode(bool enabled) {
    const RenderMode next = enabled ? RenderMode::Pixel : RenderMode::Live2d;
    if (next == renderMode_) {
        return true;
    }
    if (enabled && !pixelAvailable()) {
        return false;
    }
    if (enabled) {
        if (width() > 0 && height() > 0) {
            live2dWindowSize_ = size();
        }
        renderMode_ = RenderMode::Pixel;
        renderTimer_.stop();
        defaultStateTimer_.stop();
        setFixedSize(pixelFrameSize_);
        setPixelAnimation(QStringLiteral("idle"));
        if (!dragLocked_ && isVisible()) {
            choosePixelWanderTarget();
            pixelWanderTimer_.start();
        }
        update();
        return true;
    }

    renderMode_ = RenderMode::Live2d;
    pixelAnimationTimer_.stop();
    pixelWanderTimer_.stop();
    if (live2dWindowSize_.isValid()) {
        setFixedSize(live2dWindowSize_);
    }
    if (context() != nullptr && host_ == nullptr) {
        makeCurrent();
        const bool loaded = initializeLive2dRuntime();
        doneCurrent();
        if (!loaded) {
            renderMode_ = RenderMode::Pixel;
            setFixedSize(pixelFrameSize_);
            restartPixelAnimationTimer();
            alphaHitTimer_.start();
            if (!dragLocked_ && isVisible()) {
                choosePixelWanderTarget();
                pixelWanderTimer_.start();
            }
            return false;
        }
    }
    renderTimer_.start();
    update();
    return true;
}

bool Live2dGlWidget::pixelMode() const {
    return renderMode_ == RenderMode::Pixel;
}

bool Live2dGlWidget::pixelAvailable() const {
    return !pixelSheet_.isNull() && !pixelSheetImage_.isNull()
        && !pixelAnimations_.isEmpty() && pixelFrameSize_.isValid();
}

QSize Live2dGlWidget::pixelFrameSize() const {
    return pixelFrameSize_;
}

void Live2dGlWidget::setLive2dWindowSize(const QSize& size) {
    if (!size.isValid()) {
        return;
    }
    live2dWindowSize_ = size;
    if (!pixelMode()) {
        setFixedSize(size);
    }
}

bool Live2dGlWidget::triggerAction(const QString& action, const QString& character) {
    if (pixelMode()) {
        const QString normalized = action.trimmed().toLower();
        QString animation;
        if (pixelAnimations_.contains(action)) {
            animation = action;
        } else if (normalized.contains(QStringLiteral("fail"))) {
            animation = QStringLiteral("failed");
        } else if (normalized.contains(QStringLiteral("jump"))
                   || normalized.contains(QStringLiteral("poke"))) {
            animation = QStringLiteral("jumping");
        } else if (normalized.contains(QStringLiteral("wave"))
                   || normalized == QStringLiteral("__random__")) {
            animation = QStringLiteral("waving");
        } else if (normalized.contains(QStringLiteral("wait"))) {
            animation = QStringLiteral("waiting");
        } else {
            animation = QStringLiteral("review");
        }
        setPixelAnimation(animation);
        return pixelAnimations_.contains(animation);
    }
    if (host_ == nullptr || action.trimmed().isEmpty()) {
        return false;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    const QByteArray actionUtf8 = action.toUtf8();
    const QByteArray characterUtf8 = character.toUtf8();
    const bool triggered = bandori_live2d_trigger_action(
        host_, actionUtf8.constData(), characterUtf8.constData());
    if (!triggered) {
        reportLastError("trigger action");
    }
    if (needsCurrent) {
        doneCurrent();
    }
    if (triggered) {
        update();
        const std::uint64_t token = ++interactionExpressionToken_;
        QTimer::singleShot(
            5'000,
            this,
            [this, token]() { resetInteractionExpression(token); });
    }
    return triggered;
}

bool Live2dGlWidget::triggerExpressionTag(
    const QString& action,
    const QString& character,
    int holdMilliseconds) {
    if (pixelMode() || host_ == nullptr || action.trimmed().isEmpty()) {
        return false;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    const QByteArray actionUtf8 = action.toUtf8();
    const QByteArray characterUtf8 = character.toUtf8();
    const bool triggered = bandori_live2d_trigger_expression_tag(
        host_, actionUtf8.constData(), characterUtf8.constData());
    if (needsCurrent) {
        doneCurrent();
    }
    if (triggered) {
        update();
        const std::uint64_t token = ++interactionExpressionToken_;
        QTimer::singleShot(
            std::clamp(holdMilliseconds, 1, 60'000),
            this,
            [this, token]() { resetInteractionExpression(token); });
    }
    return triggered;
}

bool Live2dGlWidget::triggerMotionTag(
    const QString& action,
    const QString& character) {
    if (pixelMode() || host_ == nullptr || action.trimmed().isEmpty()) {
        return false;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    const QByteArray actionUtf8 = action.toUtf8();
    const QByteArray characterUtf8 = character.toUtf8();
    const bool triggered = bandori_live2d_trigger_motion_tag(
        host_, actionUtf8.constData(), characterUtf8.constData());
    if (needsCurrent) {
        doneCurrent();
    }
    if (triggered) {
        update();
    }
    return triggered;
}

bool Live2dGlWidget::applyDefaultState(
    const QString& configuredMotion,
    const QString& configuredExpression,
    const QString& character,
    bool idleActionsEnabled,
    bool randomActionsEnabled) {
    configuredDefaultMotion_ = configuredMotion.trimmed();
    configuredDefaultExpression_ = configuredExpression.trimmed();
    defaultStateCharacter_ = character.trimmed();
    idleActionsEnabled_ = idleActionsEnabled;
    randomActionsEnabled_ = randomActionsEnabled;
    defaultStateChoice_ = 0;
    if (pixelMode()) {
        setPixelAnimation(QStringLiteral("idle"));
        return true;
    }
    if (host_ == nullptr) {
        return false;
    }
    const bool motionApplied = applyDefaultStateNow(true, false);
    const bool expressionApplied = applyDefaultStateNow(false, true);
    if (idleActionsEnabled_ && motionApplied) {
        defaultStateTimer_.start();
    } else {
        defaultStateTimer_.stop();
    }
    return motionApplied || expressionApplied;
}

bool Live2dGlWidget::applyDefaultStateNow(bool applyMotion, bool applyExpression) {
    if (host_ == nullptr) {
        return false;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    const QByteArray motionUtf8 = configuredDefaultMotion_.toUtf8();
    const QByteArray expressionUtf8 = configuredDefaultExpression_.toUtf8();
    const QByteArray characterUtf8 = defaultStateCharacter_.toUtf8();
    const std::uint64_t choice = applyMotion && randomActionsEnabled_
        ? defaultStateChoice_++
        : 0;
    const std::int32_t result = bandori_live2d_apply_default_state(
        host_,
        motionUtf8.constData(),
        expressionUtf8.constData(),
        characterUtf8.constData(),
        idleActionsEnabled_,
        choice,
        applyMotion,
        applyExpression);
    if (result < 0) {
        reportLastError("apply default state");
    }
    if (needsCurrent) {
        doneCurrent();
    }
    if (result > 0) {
        update();
    }
    return result > 0;
}

void Live2dGlWidget::restoreDefaultMotionIfFinished() {
    if (host_ == nullptr || !idleActionsEnabled_) {
        defaultStateTimer_.stop();
        return;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    const std::int32_t finished = bandori_live2d_is_motion_finished(host_);
    if (finished < 0) {
        reportLastError("query motion completion");
        defaultStateTimer_.stop();
    }
    if (needsCurrent) {
        doneCurrent();
    }
    if (finished > 0 && !applyDefaultStateNow(true, false)) {
        defaultStateTimer_.stop();
    }
}

bool Live2dGlWidget::triggerInteraction(
    const QString& region,
    const QString& configuredMotion,
    const QString& configuredExpression,
    const QString& character) {
    if (pixelMode()) {
        const QString normalized = region.trimmed().toLower();
        setPixelAnimation(
            normalized.contains(QStringLiteral("head"))
                ? QStringLiteral("waving")
                : QStringLiteral("jumping"));
        return true;
    }
    if (host_ == nullptr || region.trimmed().isEmpty()) {
        return false;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    const QByteArray regionUtf8 = region.toUtf8();
    const QByteArray motionUtf8 = configuredMotion.toUtf8();
    const QByteArray expressionUtf8 = configuredExpression.toUtf8();
    const QByteArray characterUtf8 = character.toUtf8();
    const std::int32_t result = bandori_live2d_trigger_interaction(
        host_,
        regionUtf8.constData(),
        motionUtf8.constData(),
        expressionUtf8.constData(),
        characterUtf8.constData());
    if (result < 0) {
        reportLastError("trigger interaction");
    }
    if (needsCurrent) {
        doneCurrent();
    }
    if (result > 0) {
        update();
        if (!configuredExpression.trimmed().isEmpty()) {
            const std::uint64_t token = ++interactionExpressionToken_;
            QTimer::singleShot(
                5'000,
                this,
                [this, token]() { resetInteractionExpression(token); });
        }
    }
    return result > 0;
}

void Live2dGlWidget::initializeGL() {
    auto* gl = context()->functions();
    gl->initializeOpenGLFunctions();
    context()->extraFunctions()->initializeOpenGLFunctions();
    gl->glDisable(GL_DEPTH_TEST);
    gl->glDisable(GL_DITHER);

    frameClock_.start();
    lastFrameMsec_ = 0;
    alphaHitTimer_.start();
    if (pixelMode()) {
        restartPixelAnimationTimer();
        if (!dragLocked_) {
            choosePixelWanderTarget();
            pixelWanderTimer_.start();
        }
        emit runtimeReady();
        return;
    }
    initializeLive2dRuntime();
}

bool Live2dGlWidget::initializeLive2dRuntime() {
    if (host_ != nullptr) {
        return true;
    }

    const QByteArray projectRoot = projectRoot_.toUtf8();
    const QByteArray userModelsRoot = userModelsRoot_.toUtf8();
    host_ = bandori_live2d_create(
        projectRoot.constData(),
        userModelsRoot.constData(),
        static_cast<std::uint32_t>(format_),
        static_cast<std::uint32_t>(std::max(width(), 1)),
        static_cast<std::uint32_t>(std::max(height(), 1)),
        &Live2dGlWidget::resolveGlProcedure,
        this);
    if (host_ == nullptr) {
        reportLastError("create");
        return false;
    }

    const QByteArray modelPath = modelPath_.toUtf8();
    if (!bandori_live2d_load_model(
            host_,
            modelPath.constData(),
            static_cast<std::uint32_t>(std::max(width(), 1)),
            static_cast<std::uint32_t>(std::max(height(), 1)),
            textureQuality_)) {
        reportLastError("load model");
        disposeRuntime();
        return false;
    }
    if (format_ == ModelFormat::Moc3 && !bandori_live2d_set_scale(host_, 1.35)) {
        reportLastError("set Cubism 3 scale");
    }

    connect(
        context(),
        &QOpenGLContext::aboutToBeDestroyed,
        this,
        &Live2dGlWidget::disposeRuntime,
        static_cast<Qt::ConnectionType>(Qt::DirectConnection | Qt::UniqueConnection));
    frameClock_.start();
    lastFrameMsec_ = 0;
    renderTimer_.start();
    alphaHitTimer_.start();
    emit runtimeReady();
    return true;
}

void Live2dGlWidget::resizeGL(int width, int height) {
    if (pixelMode()) {
        return;
    }
    if (host_ == nullptr) {
        return;
    }
    const auto logicalWidth = static_cast<std::uint32_t>(std::max(width, 1));
    const auto logicalHeight = static_cast<std::uint32_t>(std::max(height, 1));
    if (!bandori_live2d_resize(host_, logicalWidth, logicalHeight)) {
        reportLastError("resize logical model");
        return;
    }
    if (format_ == ModelFormat::Moc3) {
        const qreal ratio = std::max<qreal>(devicePixelRatioF(), 1.0);
        const QSize renderSize(
            std::max(1, qRound(width * ratio)) * ssaaScale_,
            std::max(1, qRound(height * ratio)) * ssaaScale_);
        rendererTargetSize_ = {};
        if (!syncRendererTarget(renderSize)) {
            reportLastError("resize physical renderer");
        }
    }
}

void Live2dGlWidget::paintGL() {
    const qreal ratio = std::max<qreal>(devicePixelRatioF(), 1.0);
    const QSize targetSize(
        std::max(1, qRound(width() * ratio)),
        std::max(1, qRound(height() * ratio)));
    if (pixelMode()) {
        clearTarget(targetSize);
        if (pixelAvailable()) {
            const QJsonObject animation = activePixelAnimation();
            const int row = std::clamp(
                animation.value(QStringLiteral("row")).toInt(),
                0,
                std::max(pixelTotalRows_ - 1, 0));
            const int frame = std::clamp(
                pixelFrameIndex_, 0, std::max(pixelTotalColumns_ - 1, 0));
            const QRect source(
                frame * pixelFrameSize_.width(),
                row * pixelFrameSize_.height(),
                pixelFrameSize_.width(),
                pixelFrameSize_.height());
            QPainter painter(this);
            painter.setRenderHint(QPainter::SmoothPixmapTransform, false);
            painter.drawPixmap(rect(), pixelSheet_, source);
        }
        readPendingAlphaSample(targetSize);
        return;
    }
    if (host_ == nullptr) {
        clearTarget(targetSize);
        readPendingAlphaSample(targetSize);
        return;
    }

    bool usingSsaa = false;
    if (format_ == ModelFormat::Moc3) {
        const QSize ssaaSize = targetSize * ssaaScale_;
        usingSsaa = ssaaScale_ > 1 && ensureSsaaFramebuffer(ssaaSize);
        const QSize renderSize = usingSsaa ? ssaaSize : targetSize;
        if (!syncRendererTarget(renderSize)) {
            reportLastError("synchronize renderer target");
            renderTimer_.stop();
            return;
        }
    }
    if (!usingSsaa) {
        context()->extraFunctions()->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
    }
    clearTarget(usingSsaa ? ssaaFramebufferSize_ : targetSize);

    const qint64 now = frameClock_.elapsed();
    const double delta = lastFrameMsec_ > 0
        ? std::clamp((now - lastFrameMsec_) / 1000.0, 0.0, 0.1)
        : 0.0;
    lastFrameMsec_ = now;
    applyGazeTracking();
    const bool lipSyncFresh = now - lipSyncLastMsec_ <= 180;
    const double lipTarget = lipSyncFresh ? lipSyncTarget_ : 0.0;
    const double lipFormTarget = lipSyncFresh ? lipSyncFormTarget_ : 0.0;
    lipSyncLevel_ += (lipTarget - lipSyncLevel_) * 0.55;
    lipSyncForm_ += (lipFormTarget - lipSyncForm_) * 0.45;
    if (lipSyncLevel_ < 0.01) {
        lipSyncLevel_ = 0.0;
    }
    if (std::abs(lipSyncForm_) < 0.01) {
        lipSyncForm_ = 0.0;
    }
    if (!bandori_live2d_set_parameter(host_, "PARAM_MOUTH_OPEN_Y", lipSyncLevel_, 1.0)
        || !bandori_live2d_set_parameter(host_, "PARAM_MOUTH_FORM", lipSyncForm_, 1.0)) {
        if (usingSsaa) {
            ssaaFramebuffer_->release();
            context()->extraFunctions()->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
        }
        reportLastError("apply lip sync");
        renderTimer_.stop();
        return;
    }
    if (!bandori_live2d_draw(host_, static_cast<double>(now), delta)) {
        if (usingSsaa) {
            ssaaFramebuffer_->release();
            context()->extraFunctions()->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
        }
        reportLastError("draw frame");
        renderTimer_.stop();
        return;
    }
    if (usingSsaa) {
        ssaaFramebuffer_->release();
        if (!blitSsaaToDefault(targetSize)) {
            reportLastError("SSAA fallback render");
            renderTimer_.stop();
            return;
        }
    }
    readPendingAlphaSample(targetSize);
}

void Live2dGlWidget::mousePressEvent(QMouseEvent* event) {
    const QPoint globalPosition = event->globalPosition().toPoint();
    const bool nativeRightClick = event->button() == Qt::RightButton;
#ifdef Q_OS_MACOS
    const bool nativeControlClick = event->button() == Qt::LeftButton
        && event->modifiers().testFlag(Qt::ControlModifier);
#else
    const bool nativeControlClick = false;
#endif
    if (nativeRightClick || nativeControlClick) {
        const bool hit = isOpaqueAtGlobal(globalPosition);
        rightPressHandled_ = nativeRightClick && hit;
        if (hit) {
            setInputPassthrough(false);
            emit rightClicked(globalPosition.x(), globalPosition.y());
            event->accept();
            return;
        }
        QOpenGLWidget::mousePressEvent(event);
        return;
    }
    if (event->button() != Qt::LeftButton) {
        QOpenGLWidget::mousePressEvent(event);
        return;
    }
    pressedOnModel_ = isOpaqueAtGlobal(globalPosition);
    if (!pressedOnModel_) {
        QOpenGLWidget::mousePressEvent(event);
        return;
    }
    setInputPassthrough(false);
    if (dragLocked_) {
        event->accept();
        return;
    }
    draggingWindow_ = true;
    dragMoved_ = false;
    dragPressGlobal_ = globalPosition;
    dragWindowOrigin_ = window()->pos();
    emit windowDragStarted();
    event->accept();
}

void Live2dGlWidget::mouseMoveEvent(QMouseEvent* event) {
    if (draggingWindow_ && (event->buttons() & Qt::LeftButton)) {
        const QPoint total = event->globalPosition().toPoint() - dragPressGlobal_;
        if (!dragMoved_
            && total.x() * total.x() + total.y() * total.y() < kDragThresholdSquared) {
            event->accept();
            return;
        }
        dragMoved_ = true;
        window()->move(dragWindowOrigin_ + total);
        const QPoint actual = window()->pos() - dragWindowOrigin_;
        emit windowDragMoved(actual.x(), actual.y());
        event->accept();
        return;
    }
    QOpenGLWidget::mouseMoveEvent(event);
}

void Live2dGlWidget::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::RightButton) {
        if (rightPressHandled_) {
            rightPressHandled_ = false;
            event->accept();
            return;
        }
        QOpenGLWidget::mouseReleaseEvent(event);
        return;
    }
    if (event->button() != Qt::LeftButton || (!pressedOnModel_ && !draggingWindow_)) {
        QOpenGLWidget::mouseReleaseEvent(event);
        return;
    }
    const bool shouldClick = pressedOnModel_ && !dragMoved_;
    pressedOnModel_ = false;
    finishWindowDrag();
    dragMoved_ = false;
    if (shouldClick) {
        const QPointF position = event->position();
        emit clicked(position.x(), position.y());
    }
    event->accept();
}

void Live2dGlWidget::mouseDoubleClickEvent(QMouseEvent* event) {
    if (event->button() != Qt::LeftButton
        || !isOpaqueAtGlobal(event->globalPosition().toPoint())) {
        QOpenGLWidget::mouseDoubleClickEvent(event);
        return;
    }
    pressedOnModel_ = false;
    finishWindowDrag();
    dragMoved_ = false;
    const QPointF position = event->position();
    emit doubleClicked(position.x(), position.y());
    event->accept();
}

void Live2dGlWidget::showEvent(QShowEvent* event) {
    QOpenGLWidget::showEvent(event);
    if (!pixelMode()) {
        renderTimer_.start();
        return;
    }
    restartPixelAnimationTimer();
    if (!dragLocked_) {
        choosePixelWanderTarget();
        pixelWanderTimer_.start();
    }
}

void Live2dGlWidget::hideEvent(QHideEvent* event) {
    renderTimer_.stop();
    pixelAnimationTimer_.stop();
    pixelWanderTimer_.stop();
    QOpenGLWidget::hideEvent(event);
}

void Live2dGlWidget::enterEvent(QEnterEvent* event) {
    pixelHovering_ = true;
    if (pixelMode()) {
        setPixelAnimation(QStringLiteral("waiting"));
    }
    QOpenGLWidget::enterEvent(event);
}

void Live2dGlWidget::leaveEvent(QEvent* event) {
    pixelHovering_ = false;
    if (pixelMode()) {
        choosePixelWanderTarget();
    }
    QOpenGLWidget::leaveEvent(event);
}

QJsonObject Live2dGlWidget::activePixelAnimation() const {
    return pixelAnimations_.value(pixelAnimation_).toObject();
}

void Live2dGlWidget::setPixelAnimation(const QString& requestedName) {
    QString name = requestedName;
    if (!pixelAnimations_.contains(name)) {
        name = pixelAnimations_.contains(QStringLiteral("idle"))
            ? QStringLiteral("idle")
            : pixelAnimations_.keys().value(0);
    }
    if (name.isEmpty()) {
        return;
    }
    if (pixelAnimation_ == name && pixelAnimationTimer_.isActive()) {
        return;
    }
    pixelAnimation_ = name;
    pixelFrameIndex_ = 0;
    restartPixelAnimationTimer();
    update();
}

void Live2dGlWidget::restartPixelAnimationTimer() {
    if (!pixelMode() || !pixelAvailable()) {
        pixelAnimationTimer_.stop();
        return;
    }
    const int fps = std::clamp(
        activePixelAnimation().value(QStringLiteral("fps")).toInt(8), 1, 60);
    pixelAnimationTimer_.start(
        std::max(1, qRound(1000.0 / fps * kPixelFrameHoldBeats)));
}

void Live2dGlWidget::advancePixelFrame() {
    const QJsonObject animation = activePixelAnimation();
    const int frames = std::clamp(
        animation.value(QStringLiteral("frames")).toInt(1),
        1,
        std::max(pixelTotalColumns_, 1));
    ++pixelFrameIndex_;
    if (pixelFrameIndex_ >= frames) {
        if (animation.value(QStringLiteral("loop")).toBool(true)) {
            pixelFrameIndex_ = 0;
        } else {
            setPixelAnimation(QStringLiteral("idle"));
            return;
        }
    }
    update();
}

void Live2dGlWidget::choosePixelWanderTarget() {
    pixelWaitingForTarget_ = false;
    QScreen* screen = QGuiApplication::screenAt(window()->geometry().center());
    if (screen == nullptr) {
        screen = QGuiApplication::primaryScreen();
    }
    if (screen == nullptr) {
        pixelWanderTarget_ = window()->pos();
        return;
    }
    const QRect available = screen->availableGeometry();
    const int maximumX = std::max(available.left(), available.right() - window()->width() + 1);
    const int maximumY = std::max(available.top(), available.bottom() - window()->height() + 1);
    pixelWanderTarget_ = {
        QRandomGenerator::global()->bounded(available.left(), maximumX + 1),
        QRandomGenerator::global()->bounded(available.top(), maximumY + 1),
    };
}

void Live2dGlWidget::stepPixelWander() {
    if (!pixelMode() || dragLocked_ || draggingWindow_ || !isVisible()) {
        return;
    }
    if (pixelHovering_) {
        setPixelAnimation(QStringLiteral("waiting"));
        return;
    }
    if (pixelWaitingForTarget_) {
        return;
    }
    const QPoint position = window()->pos();
    if ((position - pixelWanderTarget_).manhattanLength() < 8) {
        QStringList resting {QStringLiteral("idle"), QStringLiteral("waiting")};
        if (pixelAnimations_.contains(QStringLiteral("review"))) {
            resting.append(QStringLiteral("review"));
        }
        setPixelAnimation(
            resting.at(QRandomGenerator::global()->bounded(
                static_cast<int>(resting.size()))));
        pixelWaitingForTarget_ = true;
        QTimer::singleShot(
            QRandomGenerator::global()->bounded(1'200, 3'501),
            this,
            &Live2dGlWidget::choosePixelWanderTarget);
        return;
    }
    const int deltaX = pixelWanderTarget_.x() - position.x();
    const int deltaY = pixelWanderTarget_.y() - position.y();
    const int stepX = std::clamp(deltaX, -3, 3);
    const int stepY = std::clamp(deltaY, -2, 2);
    if (stepX > 0) {
        setPixelAnimation(QStringLiteral("running_right"));
    } else if (stepX < 0) {
        setPixelAnimation(QStringLiteral("running_left"));
    } else {
        setPixelAnimation(QStringLiteral("running_alt"));
    }
    window()->move(position + QPoint(stepX, stepY));
}

int Live2dGlWidget::pixelAlphaAt(const QPoint& localPosition) const {
    if (!pixelAvailable() || !rect().contains(localPosition)) {
        return 0;
    }
    const QJsonObject animation = activePixelAnimation();
    const int row = std::clamp(
        animation.value(QStringLiteral("row")).toInt(),
        0,
        std::max(pixelTotalRows_ - 1, 0));
    const int frame = std::clamp(
        pixelFrameIndex_, 0, std::max(pixelTotalColumns_ - 1, 0));
    const int sourceX = frame * pixelFrameSize_.width()
        + localPosition.x() * pixelFrameSize_.width() / std::max(width(), 1);
    const int sourceY = row * pixelFrameSize_.height()
        + localPosition.y() * pixelFrameSize_.height() / std::max(height(), 1);
    if (sourceX < 0 || sourceY < 0 || sourceX >= pixelSheetImage_.width()
        || sourceY >= pixelSheetImage_.height()) {
        return 0;
    }
    return qAlpha(pixelSheetImage_.pixel(sourceX, sourceY));
}

void Live2dGlWidget::finishWindowDrag() {
    if (!draggingWindow_) {
        return;
    }
    const QPoint actual = window()->pos() - dragWindowOrigin_;
    draggingWindow_ = false;
    emit windowDragFinished(actual.x(), actual.y());
}

void Live2dGlWidget::resetInteractionExpression(std::uint64_t token) {
    if (token != interactionExpressionToken_ || host_ == nullptr) {
        return;
    }
    applyDefaultStateNow(false, true);
    update();
}

std::uintptr_t Live2dGlWidget::resolveGlProcedure(const char* name, void*) {
    QOpenGLContext* context = QOpenGLContext::currentContext();
    if (context == nullptr || name == nullptr) {
        return 0;
    }
    const QFunctionPointer procedure = context->getProcAddress(QByteArray(name));
    return reinterpret_cast<std::uintptr_t>(procedure);
}

bool Live2dGlWidget::ensureSsaaFramebuffer(const QSize& size) {
    if (ssaaFramebuffer_ == nullptr || ssaaFramebufferSize_ != size) {
        ssaaFramebuffer_.reset();
        QOpenGLFramebufferObjectFormat format;
        format.setAttachment(QOpenGLFramebufferObject::CombinedDepthStencil);
        format.setSamples(0);
        ssaaFramebuffer_ = std::make_unique<QOpenGLFramebufferObject>(size, format);
        ssaaFramebufferSize_ = size;
    }
    if (!ssaaFramebuffer_->isValid() || !ssaaFramebuffer_->bind()) {
        ssaaFramebuffer_.reset();
        ssaaFramebufferSize_ = {};
        return false;
    }
    return true;
}

bool Live2dGlWidget::syncRendererTarget(const QSize& size) {
    if (rendererTargetSize_ == size) {
        return true;
    }
    if (!bandori_live2d_resize_renderer(
            host_,
            static_cast<std::uint32_t>(size.width()),
            static_cast<std::uint32_t>(size.height()))) {
        return false;
    }
    rendererTargetSize_ = size;
    return true;
}

bool Live2dGlWidget::blitSsaaToDefault(const QSize& targetSize) {
    auto* gl = context()->functions();
    auto* extra = context()->extraFunctions();
    while (gl->glGetError() != GL_NO_ERROR) {
    }
    extra->glBindFramebuffer(GL_READ_FRAMEBUFFER, ssaaFramebuffer_->handle());
    extra->glBindFramebuffer(GL_DRAW_FRAMEBUFFER, defaultFramebufferObject());
    clearTarget(targetSize);
    extra->glBlitFramebuffer(
        0,
        0,
        ssaaFramebufferSize_.width(),
        ssaaFramebufferSize_.height(),
        0,
        0,
        targetSize.width(),
        targetSize.height(),
        GL_COLOR_BUFFER_BIT,
        GL_LINEAR);
    extra->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
    if (gl->glGetError() == GL_NO_ERROR) {
        return true;
    }

    // The simulation already advanced into the SSAA target. If the driver
    // cannot blit it, draw that exact state again at native resolution.
    ssaaFramebuffer_.reset();
    ssaaFramebufferSize_ = {};
    rendererTargetSize_ = {};
    if (!syncRendererTarget(targetSize)) {
        return false;
    }
    clearTarget(targetSize);
    return bandori_live2d_render_only(host_);
}

void Live2dGlWidget::clearTarget(const QSize& size) {
    auto* gl = context()->functions();
    auto* extra = context()->extraFunctions();
    gl->glViewport(0, 0, size.width(), size.height());
    gl->glEnable(GL_BLEND);
    extra->glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD);
    gl->glClearColor(0.0F, 0.0F, 0.0F, 0.0F);
    gl->glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
}

void Live2dGlWidget::applyGazeTracking() {
    if (host_ == nullptr || draggingWindow_) {
        return;
    }
    QPoint target;
    if (gazeTargetGlobal_.has_value()) {
        target = *gazeTargetGlobal_;
    } else if (headTrackingEnabled_) {
        target = QCursor::pos();
    } else {
        return;
    }
    const QPoint windowOrigin = mapToGlobal(QPoint(0, 0));
    if (gazeWasApplied_ && target == lastAppliedGazeGlobal_
        && windowOrigin == lastAppliedGazeWindowOrigin_) {
        return;
    }
    const QPointF center(width() * 0.5, height() * 0.5);
    const QPointF targetLocal = QPointF(target - windowOrigin);
    QPointF direction = targetLocal - center;
    const double distance = std::hypot(direction.x(), direction.y());
    if (distance > 600.0) {
        direction *= 600.0 / distance;
    }
    const QPointF local = center + direction;
    if (!bandori_live2d_drag(host_, local.x(), local.y())) {
        reportLastError("update gaze");
        return;
    }
    lastAppliedGazeGlobal_ = target;
    lastAppliedGazeWindowOrigin_ = windowOrigin;
    gazeWasApplied_ = true;
}

void Live2dGlWidget::requestAlphaSample() {
    if (!isVisible()) {
        setInputPassthrough(false);
        return;
    }
    if (draggingWindow_ || QGuiApplication::mouseButtons() != Qt::NoButton) {
        setInputPassthrough(false);
        return;
    }
    const QPoint globalPosition = QCursor::pos();
    const QPoint localPosition = mapFromGlobal(globalPosition);
    if (!rect().contains(localPosition)) {
        alphaSamplePending_ = false;
        lastAlphaSampleValid_ = false;
        setInputPassthrough(false);
        return;
    }
    pendingAlphaSampleGlobal_ = globalPosition;
    alphaSamplePending_ = true;
    update();
}

void Live2dGlWidget::readPendingAlphaSample(const QSize& targetSize) {
    if (!alphaSamplePending_) {
        return;
    }
    alphaSamplePending_ = false;
    const QPoint localPosition = mapFromGlobal(pendingAlphaSampleGlobal_);
    if (!rect().contains(localPosition)) {
        lastAlphaSampleValid_ = false;
        return;
    }
    if (pixelMode()) {
        lastAlphaSampleGlobal_ = pendingAlphaSampleGlobal_;
        lastAlphaSampleOpaque_ = pixelAlphaAt(localPosition) > hitAlphaThreshold_;
        lastAlphaSampleValid_ = true;
        QTimer::singleShot(0, this, &Live2dGlWidget::applyInputPassthroughFromSample);
        return;
    }
    const qreal ratio = std::max<qreal>(devicePixelRatioF(), 1.0);
    const int sampleX = std::clamp(
        qFloor(localPosition.x() * ratio), 0, std::max(targetSize.width() - 1, 0));
    const int sampleY = std::clamp(
        targetSize.height() - 1 - qFloor(localPosition.y() * ratio),
        0,
        std::max(targetSize.height() - 1, 0));
    unsigned char pixel[4] {};
    context()->extraFunctions()->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
    context()->functions()->glReadPixels(
        sampleX, sampleY, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    lastAlphaSampleGlobal_ = pendingAlphaSampleGlobal_;
    lastAlphaSampleOpaque_ = pixel[3] > hitAlphaThreshold_;
    lastAlphaSampleValid_ = true;
    QTimer::singleShot(0, this, &Live2dGlWidget::applyInputPassthroughFromSample);
}

bool Live2dGlWidget::isOpaqueAtGlobal(const QPoint& globalPosition) {
    const QPoint localPosition = mapFromGlobal(globalPosition);
    if (!rect().contains(localPosition)) {
        return false;
    }
    if (pixelMode()) {
        constexpr QPoint probes[] {
            {0, 0}, {-2, 0}, {2, 0}, {0, -2}, {0, 2},
            {-4, 0}, {4, 0}, {0, -4}, {0, 4},
        };
        return std::any_of(std::begin(probes), std::end(probes), [this, localPosition](QPoint offset) {
            return pixelAlphaAt(localPosition + offset) > hitAlphaThreshold_;
        });
    }
    if (context() == nullptr) {
        return false;
    }
    const bool needsCurrent = QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    const qreal ratio = std::max<qreal>(devicePixelRatioF(), 1.0);
    const QSize targetSize(
        std::max(1, qRound(width() * ratio)),
        std::max(1, qRound(height() * ratio)));
    const int sampleX = std::clamp(
        qFloor(localPosition.x() * ratio), 0, targetSize.width() - 1);
    const int sampleY = std::clamp(
        targetSize.height() - 1 - qFloor(localPosition.y() * ratio),
        0,
        targetSize.height() - 1);
    unsigned char pixel[4] {};
    context()->extraFunctions()->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
    context()->functions()->glReadPixels(
        sampleX, sampleY, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    if (needsCurrent) {
        doneCurrent();
    }
    return pixel[3] > hitAlphaThreshold_;
}

void Live2dGlWidget::applyInputPassthroughFromSample() {
    if (!lastAlphaSampleValid_ || draggingWindow_
        || QGuiApplication::mouseButtons() != Qt::NoButton) {
        setInputPassthrough(false);
        return;
    }
    const QPoint cursor = QCursor::pos();
    if (cursor != lastAlphaSampleGlobal_) {
        setInputPassthrough(false);
        return;
    }
    const qint64 now = frameClock_.isValid() ? frameClock_.elapsed() : 0;
    if (lastAlphaSampleOpaque_) {
        lastOpaqueMsec_ = now;
        lastOpaqueGlobal_ = cursor;
        setInputPassthrough(false);
        return;
    }
    const QPoint distance = cursor - lastOpaqueGlobal_;
    const bool insideGrace = now - lastOpaqueMsec_ < kAlphaHitGraceMsec
        && distance.x() * distance.x() + distance.y() * distance.y()
            <= kAlphaHitGraceDistance * kAlphaHitGraceDistance;
    setInputPassthrough(!insideGrace);
}

void Live2dGlWidget::setInputPassthrough(bool enabled) {
    if (enabled && (draggingWindow_ || QGuiApplication::mouseButtons() != Qt::NoButton)) {
        enabled = false;
    }
    if (inputPassthrough_ == enabled) {
        return;
    }
#ifdef Q_OS_WIN
    const HWND handle = reinterpret_cast<HWND>(window()->winId());
    if (handle == nullptr) {
        return;
    }
    const LONG_PTR style = GetWindowLongPtrW(handle, GWL_EXSTYLE);
    const LONG_PTR nextStyle = enabled ? style | WS_EX_TRANSPARENT : style & ~WS_EX_TRANSPARENT;
    if (nextStyle != style) {
        SetWindowLongPtrW(handle, GWL_EXSTYLE, nextStyle);
        SetWindowPos(
            handle,
            nullptr,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
    }
#else
    QWindow* nativeWindow = window()->windowHandle();
    if (nativeWindow == nullptr) {
        return;
    }
    nativeWindow->setFlag(Qt::WindowTransparentForInput, enabled);
#endif
    inputPassthrough_ = enabled;
}

void Live2dGlWidget::disposeRuntime() {
    renderTimer_.stop();
    alphaHitTimer_.stop();
    defaultStateTimer_.stop();
    pixelAnimationTimer_.stop();
    pixelWanderTimer_.stop();
    setInputPassthrough(false);
    if (host_ == nullptr) {
        return;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    ssaaFramebuffer_.reset();
    ssaaFramebufferSize_ = {};
    rendererTargetSize_ = {};
    bandori_live2d_destroy(host_);
    host_ = nullptr;
    if (needsCurrent) {
        doneCurrent();
    }
}

void Live2dGlWidget::reportLastError(const char* operation) {
    qWarning().noquote() << "Live2D" << operation << "failed:" << bandori_live2d_last_error();
}

} // namespace bandori
