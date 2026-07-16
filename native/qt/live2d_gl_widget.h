#pragma once

#include "bandori_live2d_ffi.h"

#include <QElapsedTimer>
#include <QImage>
#include <QJsonObject>
#include <QOpenGLWidget>
#include <QPoint>
#include <QPixmap>
#include <QSize>
#include <QString>
#include <QTimer>

#include <memory>
#include <optional>

class QMouseEvent;
class QOpenGLFramebufferObject;
class QEnterEvent;
class QEvent;
class QHideEvent;
class QShowEvent;

namespace bandori {

class Live2dGlWidget final : public QOpenGLWidget {
    Q_OBJECT

public:
    enum class ModelFormat : std::uint32_t {
        Moc = 2,
        Moc3 = 3,
    };

    enum class RenderMode : std::uint32_t {
        Live2d = 0,
        Pixel = 1,
    };

    static void configureDefaultSurfaceFormat(bool vsync = true);

    Live2dGlWidget(
        QString projectRoot,
        QString userModelsRoot,
        QString modelPath,
        ModelFormat format,
        RenderMode renderMode = RenderMode::Live2d,
        QWidget* parent = nullptr);
    ~Live2dGlWidget() override;

    void setFramesPerSecond(int fps);
    void setRenderQuality(const QString& quality);
    void setDragLocked(bool locked);
    bool dragLocked() const;
    void setHeadTrackingEnabled(bool enabled);
    void setGazeTargetGlobal(const QPoint& globalPosition);
    void clearGazeTarget();
    void setHitAlphaThreshold(int threshold);
    void setLipSyncMaxOpen(double value);
    void setLipSyncPose(double level, double form = 0.0);
    bool loadPixelSprite(const QString& imagePath, const QString& framesPath);
    bool setPixelMode(bool enabled);
    bool pixelMode() const;
    bool pixelAvailable() const;
    QSize pixelFrameSize() const;
    void setLive2dWindowSize(const QSize& size);
    bool triggerAction(const QString& action, const QString& character);
    bool triggerExpressionTag(
        const QString& action,
        const QString& character,
        int holdMilliseconds);
    bool triggerMotionTag(const QString& action, const QString& character);
    bool applyDefaultState(
        const QString& configuredMotion,
        const QString& configuredExpression,
        const QString& character,
        bool idleActionsEnabled,
        bool randomActionsEnabled);
    bool triggerInteraction(
        const QString& region,
        const QString& configuredMotion,
        const QString& configuredExpression,
        const QString& character);

signals:
    void runtimeReady();
    void clicked(double x, double y);
    void doubleClicked(double x, double y);
    void rightClicked(int globalX, int globalY);
    void windowDragStarted();
    void windowDragMoved(int totalDx, int totalDy);
    void windowDragFinished(int totalDx, int totalDy);

protected:
    void initializeGL() override;
    void resizeGL(int width, int height) override;
    void paintGL() override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;
    void showEvent(QShowEvent* event) override;
    void hideEvent(QHideEvent* event) override;
    void enterEvent(QEnterEvent* event) override;
    void leaveEvent(QEvent* event) override;

private:
    static std::uintptr_t resolveGlProcedure(const char* name, void* userData);
    bool initializeLive2dRuntime();
    bool ensureSsaaFramebuffer(const QSize& size);
    bool syncRendererTarget(const QSize& size);
    bool blitSsaaToDefault(const QSize& targetSize);
    void clearTarget(const QSize& size);
    void applyGazeTracking();
    void requestAlphaSample();
    void readPendingAlphaSample(const QSize& targetSize);
    bool isOpaqueAtGlobal(const QPoint& globalPosition);
    void applyInputPassthroughFromSample();
    void setInputPassthrough(bool enabled);
    void finishWindowDrag();
    void resetInteractionExpression(std::uint64_t token);
    bool applyDefaultStateNow(bool applyMotion, bool applyExpression);
    void restoreDefaultMotionIfFinished();
    void setPixelAnimation(const QString& name);
    void restartPixelAnimationTimer();
    void advancePixelFrame();
    void choosePixelWanderTarget();
    void stepPixelWander();
    int pixelAlphaAt(const QPoint& localPosition) const;
    QJsonObject activePixelAnimation() const;
    void disposeRuntime();
    void reportLastError(const char* operation);

    QString projectRoot_;
    QString userModelsRoot_;
    QString modelPath_;
    ModelFormat format_;
    RenderMode renderMode_ = RenderMode::Live2d;
    BandoriLive2dHost* host_ = nullptr;
    QElapsedTimer frameClock_;
    qint64 lastFrameMsec_ = 0;
    qint64 lipSyncLastMsec_ = -1'000;
    double lipSyncLevel_ = 0.0;
    double lipSyncTarget_ = 0.0;
    double lipSyncForm_ = 0.0;
    double lipSyncFormTarget_ = 0.0;
    double lipSyncMaxOpen_ = 0.55;
    std::uint32_t textureQuality_ = 1;
    int ssaaScale_ = 2;
    QTimer renderTimer_;
    QTimer alphaHitTimer_;
    QTimer defaultStateTimer_;
    QTimer pixelAnimationTimer_;
    QTimer pixelWanderTimer_;
    QPixmap pixelSheet_;
    QImage pixelSheetImage_;
    QJsonObject pixelAnimations_;
    QString pixelAnimation_ = QStringLiteral("idle");
    QSize pixelFrameSize_;
    QSize live2dWindowSize_;
    QPoint pixelWanderTarget_;
    int pixelTotalColumns_ = 0;
    int pixelTotalRows_ = 0;
    int pixelFrameIndex_ = 0;
    bool pixelWaitingForTarget_ = false;
    bool pixelHovering_ = false;
    QString configuredDefaultMotion_;
    QString configuredDefaultExpression_;
    QString defaultStateCharacter_;
    bool idleActionsEnabled_ = true;
    bool randomActionsEnabled_ = true;
    std::uint64_t defaultStateChoice_ = 0;
    int hitAlphaThreshold_ = 8;
    bool alphaSamplePending_ = false;
    bool lastAlphaSampleValid_ = false;
    bool lastAlphaSampleOpaque_ = false;
    bool inputPassthrough_ = false;
    QPoint pendingAlphaSampleGlobal_;
    QPoint lastAlphaSampleGlobal_;
    QPoint lastOpaqueGlobal_;
    qint64 lastOpaqueMsec_ = -1'000;
    bool draggingWindow_ = false;
    bool dragLocked_ = false;
    bool headTrackingEnabled_ = true;
    std::optional<QPoint> gazeTargetGlobal_;
    QPoint lastAppliedGazeGlobal_;
    QPoint lastAppliedGazeWindowOrigin_;
    bool gazeWasApplied_ = false;
    bool dragMoved_ = false;
    bool pressedOnModel_ = false;
    bool rightPressHandled_ = false;
    std::uint64_t interactionExpressionToken_ = 0;
    QPoint dragPressGlobal_;
    QPoint dragWindowOrigin_;
    std::unique_ptr<QOpenGLFramebufferObject> ssaaFramebuffer_;
    QSize ssaaFramebufferSize_;
    QSize rendererTargetSize_;
};

} // namespace bandori
