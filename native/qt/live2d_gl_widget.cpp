#include "live2d_gl_widget.h"

#include <QByteArray>
#include <QCursor>
#include <QDebug>
#include <QGuiApplication>
#include <QMouseEvent>
#include <QOpenGLContext>
#include <QOpenGLExtraFunctions>
#include <QOpenGLFramebufferObject>
#include <QOpenGLFramebufferObjectFormat>
#include <QOpenGLFunctions>
#include <QSurfaceFormat>
#include <QWindow>

#include <algorithm>
#include <cmath>
#include <utility>

#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#endif

namespace bandori {

namespace {
constexpr int kMoc3BalancedSsaaScale = 2;
constexpr int kAlphaHitIntervalMsec = 16;
constexpr int kAlphaHitGraceMsec = 80;
constexpr int kAlphaHitGraceDistance = 12;
constexpr int kDragThresholdSquared = 16;
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
    QWidget* parent)
    : QOpenGLWidget(parent),
      projectRoot_(std::move(projectRoot)),
      userModelsRoot_(std::move(userModelsRoot)),
      modelPath_(std::move(modelPath)),
      format_(format) {
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
    if (isVisible()) {
        renderTimer_.start();
    }
}

void Live2dGlWidget::setDragLocked(bool locked) {
    dragLocked_ = locked;
}

void Live2dGlWidget::setLipSyncMaxOpen(double value) {
    lipSyncMaxOpen_ = std::clamp(value, 0.0, 1.0);
    lipSyncTarget_ = std::clamp(lipSyncTarget_, 0.0, lipSyncMaxOpen_);
}

void Live2dGlWidget::setLipSyncPose(double level, double form) {
    lipSyncTarget_ = std::clamp(level, 0.0, lipSyncMaxOpen_);
    lipSyncFormTarget_ = std::clamp(form, -1.0, 1.0);
    lipSyncLastMsec_ = frameClock_.isValid() ? frameClock_.elapsed() : 0;
    update();
}

bool Live2dGlWidget::triggerAction(const QString& action, const QString& character) {
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
    }
    return triggered;
}

void Live2dGlWidget::initializeGL() {
    auto* gl = context()->functions();
    gl->initializeOpenGLFunctions();
    context()->extraFunctions()->initializeOpenGLFunctions();
    gl->glDisable(GL_DEPTH_TEST);
    gl->glDisable(GL_DITHER);

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
        return;
    }

    const QByteArray modelPath = modelPath_.toUtf8();
    if (!bandori_live2d_load_model(
            host_,
            modelPath.constData(),
            static_cast<std::uint32_t>(std::max(width(), 1)),
            static_cast<std::uint32_t>(std::max(height(), 1)),
            1)) {
        reportLastError("load model");
        disposeRuntime();
        return;
    }
    if (format_ == ModelFormat::Moc3 && !bandori_live2d_set_scale(host_, 1.35)) {
        reportLastError("set Cubism 3 scale");
    }

    connect(
        context(),
        &QOpenGLContext::aboutToBeDestroyed,
        this,
        &Live2dGlWidget::disposeRuntime,
        Qt::DirectConnection);
    frameClock_.start();
    lastFrameMsec_ = 0;
    renderTimer_.start();
    alphaHitTimer_.start();
}

void Live2dGlWidget::resizeGL(int width, int height) {
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
            std::max(1, qRound(width * ratio)) * kMoc3BalancedSsaaScale,
            std::max(1, qRound(height * ratio)) * kMoc3BalancedSsaaScale);
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
    if (host_ == nullptr) {
        clearTarget(targetSize);
        readPendingAlphaSample(targetSize);
        return;
    }

    bool usingSsaa = false;
    if (format_ == ModelFormat::Moc3) {
        const QSize ssaaSize = targetSize * kMoc3BalancedSsaaScale;
        usingSsaa = ensureSsaaFramebuffer(ssaaSize);
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
    if (event->button() != Qt::LeftButton) {
        QOpenGLWidget::mousePressEvent(event);
        return;
    }
    if (dragLocked_) {
        QOpenGLWidget::mousePressEvent(event);
        return;
    }
    if (!isOpaqueAtGlobal(event->globalPosition().toPoint())) {
        QOpenGLWidget::mousePressEvent(event);
        return;
    }
    setInputPassthrough(false);
    draggingWindow_ = true;
    dragMoved_ = false;
    dragPressGlobal_ = event->globalPosition().toPoint();
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
    if (host_ != nullptr) {
        const QPointF position = event->position();
        if (!bandori_live2d_drag(host_, position.x(), position.y())) {
            reportLastError("update gaze");
        }
    }
    QOpenGLWidget::mouseMoveEvent(event);
}

void Live2dGlWidget::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() != Qt::LeftButton || !draggingWindow_) {
        QOpenGLWidget::mouseReleaseEvent(event);
        return;
    }
    const QPoint actual = window()->pos() - dragWindowOrigin_;
    draggingWindow_ = false;
    emit windowDragFinished(actual.x(), actual.y());
    dragMoved_ = false;
    event->accept();
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
    if (context() == nullptr) {
        return false;
    }
    const QPoint localPosition = mapFromGlobal(globalPosition);
    if (!rect().contains(localPosition)) {
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
