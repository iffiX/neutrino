import SwiftUI

/// Views in lines, in their order: a view that does not fit on the line starts the next one. Each line is pushed
/// to the leading or the trailing edge, and the views of a line are centred on it vertically.
struct FlowRow: Layout {
    /// The space between two views of a line.
    var spacing = 8.0

    /// The space between two lines.
    var lineSpacing = 8.0

    /// Whether each line is pushed to the trailing edge.
    var isTrailing = false

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        let width = proposal.width.map { Double($0) } ?? .infinity
        let lines = Self.lines(widths: sizes.map { Double($0.width) }, width: width, spacing: spacing)
        let widest = lines.map { line in lineWidth(line, sizes) }.max() ?? 0
        let height = lines.map { line in lineHeight(line, sizes) }.reduce(0, +)
        let gaps = Double(max(lines.count - 1, 0)) * lineSpacing
        return CGSize(width: CGFloat(width.isFinite ? width : widest), height: CGFloat(height + gaps))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        let lines = Self.lines(widths: sizes.map { Double($0.width) }, width: Double(bounds.width), spacing: spacing)
        var top = Double(bounds.minY)
        for line in lines {
            let height = lineHeight(line, sizes)
            var left = Double(bounds.minX)
            if isTrailing { left = Double(bounds.maxX) - lineWidth(line, sizes) }
            for index in line {
                let size = sizes[index]
                let y = top + (height - Double(size.height)) / 2
                subviews[index].place(
                    at: CGPoint(x: left, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
                left += Double(size.width) + spacing
            }
            top += height + lineSpacing
        }
    }

    /// The lines views of these widths take in a given width: each line the indices of its views, in order. A
    /// view wider than the width takes a line of its own.
    ///
    /// - Parameters:
    ///   - widths: The views' widths, in order.
    ///   - width: The width a line has.
    ///   - spacing: The space between two views of a line.
    /// - Returns: The lines; none for no views.
    static func lines(widths: [Double], width: Double, spacing: Double) -> [[Int]] {
        var lines: [[Int]] = []
        var line: [Int] = []
        var used = 0.0
        for (index, viewWidth) in widths.enumerated() {
            let next = line.isEmpty ? viewWidth : used + spacing + viewWidth
            if !line.isEmpty && next > width {
                lines.append(line)
                line = [index]
                used = viewWidth
            } else {
                line.append(index)
                used = next
            }
        }
        if !line.isEmpty { lines.append(line) }
        return lines
    }

    private func lineWidth(_ line: [Int], _ sizes: [CGSize]) -> Double {
        line.map { Double(sizes[$0].width) }.reduce(0, +) + Double(max(line.count - 1, 0)) * spacing
    }

    private func lineHeight(_ line: [Int], _ sizes: [CGSize]) -> Double {
        line.map { Double(sizes[$0].height) }.max() ?? 0
    }
}
