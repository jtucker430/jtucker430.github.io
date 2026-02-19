/**
 * Research page tag + type filtering
 * Joshua A. Tucker academic website
 */

(function () {
  "use strict";

  var activeType = "all";
  var activeTag = "all";

  var allPubs = Array.from(document.querySelectorAll(".pub-entry"));
  var countEl = document.getElementById("pub-count");
  var clearBtn = document.getElementById("clear-filters");

  function updateDisplay() {
    var visible = 0;
    allPubs.forEach(function (pub) {
      var pubType = pub.getAttribute("data-type");
      var pubTags = pub.getAttribute("data-tags") || "";

      var typeMatch = activeType === "all" || pubType === activeType;
      var tagMatch = activeTag === "all" || pubTags.indexOf(activeTag) !== -1;

      if (typeMatch && tagMatch) {
        pub.style.display = "";
        visible++;
      } else {
        pub.style.display = "none";
      }
    });

    if (countEl) {
      countEl.textContent = visible + " publication" + (visible !== 1 ? "s" : "");
    }

    if (clearBtn) {
      clearBtn.style.display =
        activeType !== "all" || activeTag !== "all" ? "inline-block" : "none";
    }
  }

  // Type filter buttons
  document.querySelectorAll(".type-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document
        .querySelectorAll(".type-btn")
        .forEach(function (b) {
          b.classList.remove("active");
        });
      btn.classList.add("active");
      activeType = btn.getAttribute("data-type");
      updateDisplay();
    });
  });

  // Tag filter buttons
  document.querySelectorAll(".tag-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document
        .querySelectorAll(".tag-btn")
        .forEach(function (b) {
          b.classList.remove("active");
        });
      btn.classList.add("active");
      activeTag = btn.getAttribute("data-tag");
      updateDisplay();
    });
  });

  // Clicking a tag pill on a publication
  document.querySelectorAll(".pub-tag").forEach(function (pill) {
    pill.addEventListener("click", function () {
      var tag = pill.getAttribute("data-tag");
      document.querySelectorAll(".tag-btn").forEach(function (b) {
        b.classList.remove("active");
        if (b.getAttribute("data-tag") === tag) {
          b.classList.add("active");
        }
      });
      activeTag = tag;
      updateDisplay();
      // Scroll to filter controls
      var filterSection = document.querySelector(".filter-section");
      if (filterSection) {
        filterSection.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  // Clear filters
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      activeType = "all";
      activeTag = "all";
      document.querySelectorAll(".type-btn, .tag-btn").forEach(function (b) {
        b.classList.remove("active");
        if (b.getAttribute("data-type") === "all" || b.getAttribute("data-tag") === "all") {
          b.classList.add("active");
        }
      });
      updateDisplay();
    });
  }

  // Abstract toggle
  window.toggleAbstract = function (btn) {
    var abstractEl = btn.nextElementSibling;
    if (abstractEl.style.display === "none" || abstractEl.style.display === "") {
      abstractEl.style.display = "block";
      btn.textContent = "Abstract ▲";
    } else {
      abstractEl.style.display = "none";
      btn.textContent = "Abstract ▼";
    }
  };

  // Initial count
  updateDisplay();
})();
