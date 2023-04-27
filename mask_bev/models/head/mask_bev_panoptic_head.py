from typing import List

import cv2
import einops as ein
import numpy as np
import torch
import torch.nn.functional as F
from mmdet.models.utils import multi_apply
from torch import nn

from mask_bev.datasets.kitti.kitti_transforms import Difficulty
from mask_bev.evaluation.average_precision import batched_mask_iou, rot_mask_iou
from mask_bev.evaluation.detection_metric import DetectionMapMetric, BinaryClassifMapMetric, MeanIoU, MaskArea
from mask_bev.models.networks.mask2former_head.mask2former_head import Mask2FormerHead
from mask_bev.utils.config import Config


class PointMaskPanopticHead(nn.Module):
    def __init__(self, in_channels: List[int], feat_channels: int, out_channels: int, num_queries: int,
                 num_classes: int, reverse_class_weights: bool = False, predict_height: bool = False):
        super().__init__()
        config = self._get_config(num_classes, 0, num_queries, in_channels, feat_channels, out_channels,
                                  reverse_class_weights)
        self._predict_height = predict_height
        self._panoptic_head = Mask2FormerHead(**config, predict_height=self._predict_height)
        self._panoptic_head.init_weights()

    def forward(self, x):
        img_meta = [{} for _ in range(x[0].shape[0])]
        return self._panoptic_head.forward(x, img_meta)

    def loss(self, cls, masks, label_gt, masks_gt, heights_pred, heights_gt):
        img_meta = [{} for i in range(cls[0].shape[0])]
        return self._panoptic_head.loss(cls, masks, label_gt, masks_gt, img_meta, heights_pred, heights_gt)

    def add_average_precision(self, cls_metric: BinaryClassifMapMetric, height_metric: DetectionMapMetric,
                              mask_metric: DetectionMapMetric, cls_pred_score,
                              masks_pred, label_gt, mask_gt, heights_pred, heights_gt, metadata=None,
                              mAP_level: [DetectionMapMetric] = None, mIoU_metric: MeanIoU = None,
                              all_metric: [DetectionMapMetric] = None, mask_area_metric: MaskArea = None,
                              val_mIoU_points: MeanIoU = None):
        # TODO mAP per difficulty level
        def get_targets(cls_scores, masks, gt_label_list, gt_masks_list):
            num_imgs = cls_scores.size(0)
            img_meta = [{} for _ in range(num_imgs)]
            cls_scores_list = [cls_scores[i] for i in range(num_imgs)]
            mask_preds_list = [masks[i] for i in range(num_imgs)]
            heights_list_gt = [heights_gt[i] for i in range(num_imgs)]
            return self._panoptic_head.get_targets(cls_scores_list, mask_preds_list, gt_label_list, gt_masks_list,
                                                   img_meta, heights_list_gt)

        # Old way
        # num_dec_layers = len(cls_pred_score)
        # all_gt_labels_list = [label_gt for _ in range(num_dec_layers)]
        # all_gt_masks_list = [mask_gt for _ in range(num_dec_layers)]
        #
        # # TODO can only find target for last layer
        # (labels_list, label_weights_list, mask_targets_list, mask_weights_list, num_total_pos,
        #  num_total_neg) = multi_apply(get_targets, cls_pred_score, masks_pred, all_gt_labels_list, all_gt_masks_list)
        #
        # last_layer_cls_pred_score = cls_pred_score[-1]
        # last_layer_cls_pred = last_layer_cls_pred_score.argmax(dim=-1)
        #
        # cls = 1
        # iou_threshold = 0.5
        # detection_idx = torch.where(last_layer_cls_pred == cls)
        #
        # gt_for_detection = torch.stack(labels_list[-1])[detection_idx]
        # is_true_positive = (gt_for_detection == cls).long()
        #
        # confidences = last_layer_cls_pred_score[detection_idx][:, cls]
        # total_gt = (label_gt == cls).sum()
        #
        # cls_metric.update(confidences, is_true_positive, total_gt)
        #
        # # Mask mAP
        # last_layer_target_masks = torch.stack(mask_targets_list[-1])[detection_idx].long()
        #
        # target_shape = last_layer_target_masks.shape[-2:]
        # last_layer_pred_masks = masks_pred[-1][detection_idx]
        # last_layer_pred_masks = F.interpolate(
        #     last_layer_pred_masks.unsqueeze(1),
        #     target_shape,
        #     mode='bilinear',
        #     align_corners=False).squeeze(1)
        # bin_last_layer_pred_masks = torch.sigmoid(last_layer_pred_masks) > 0.5
        #
        # ious = batched_mask_iou(last_layer_target_masks, bin_last_layer_pred_masks)
        # # Do bitwise and on prediction, both cls and mask must be good at threshold
        # is_mask_respect = ious >= iou_threshold
        # is_true_positive = torch.bitwise_and(is_true_positive, is_mask_respect)
        # metric.update(confidences, is_true_positive, total_gt)
        # return
        # # end Old way

        def get_assigns(cls_score, mask_pred, gt_labels, gt_masks, img_metas):
            target_shape = mask_pred.shape[-2:]
            if gt_masks.shape[0] > 0:
                gt_masks_downsampled = F.interpolate(
                    gt_masks.unsqueeze(1).float(), target_shape,
                    mode='nearest').squeeze(1).long()
            else:
                gt_masks_downsampled = gt_masks

            # assign and sample
            assign_result = self._panoptic_head.assigner.assign(cls_score, mask_pred, gt_labels,
                                                                gt_masks_downsampled, img_metas)
            sampling_result = self._panoptic_head.sampler.sample(assign_result, mask_pred,
                                                                 gt_masks)
            return sampling_result

        def get_sampling(cls_scores, masks, gt_label_list, gt_masks_list):
            num_imgs = cls_scores.size(0)
            img_meta = [{} for _ in range(num_imgs)]
            cls_scores_list = [cls_scores[i] for i in range(num_imgs)]
            mask_preds_list = [masks[i] for i in range(num_imgs)]

            map_results = map(get_assigns, cls_scores_list, mask_preds_list, gt_label_list, gt_masks_list, img_meta)

            return map_results

        num_dec_layers = len(cls_pred_score)
        all_gt_labels_list = [label_gt for _ in range(num_dec_layers)]
        all_gt_masks_list = [mask_gt for _ in range(num_dec_layers)]

        # TODO can only find target for last layer
        (labels_list, label_weights_list, mask_targets_list, mask_weights_list, num_total_pos,
         num_total_neg, heights_list_gt) = multi_apply(get_targets, cls_pred_score, masks_pred, all_gt_labels_list,
                                                       all_gt_masks_list)

        # cls mAP
        y_true = torch.cat(labels_list[-1])
        y_score = ein.rearrange(cls_pred_score[-1], 'b n c -> (b n) c').softmax(dim=1)
        cls_metric.update(y_score, y_true)

        # height mAP
        if height_metric is not None:
            ...
            # hs = []
            # for h in heights_list_gt[-1]:
            #     hs.extend(h)
            # heights = torch.tensor(hs, device=heights_pred[-1].device)
            # heights_rounded = torch.round(heights * 5) / 5
            # pred_height = (heights_pred[-1] - 1) * 0.2 + 1
            # height_iou = torch.max(pred_height, heights_rounded) / (torch.min(pred_height, heights_rounded) + 1e-12)

        # mask mAP
        cls = 1
        iou_threshold = 0.7
        use_rot_iou = False

        num_instances = (label_gt == cls).sum()
        pred_scores = cls_pred_score[-1]
        pred_cls = pred_scores.argmax(dim=-1)
        detection_idx = torch.where(pred_cls == cls)

        confidences = pred_scores[detection_idx][:, cls]
        y_true_for_detection = torch.stack(labels_list[-1])[detection_idx]
        is_true_positive = (y_true_for_detection == cls).long()

        target_masks = torch.stack(mask_targets_list[-1])[detection_idx].long()

        target_shape = target_masks.shape[-2:]
        pred_masks = masks_pred[-1][detection_idx]
        pred_masks = F.interpolate(
            pred_masks.unsqueeze(1),
            target_shape,
            mode='bilinear',
            align_corners=False).squeeze(1)
        binary_pred_mask = torch.sigmoid(pred_masks) > 0.5

        ious = batched_mask_iou(target_masks, binary_pred_mask)
        mIoU_metric.update(ious)

        # Do bitwise and on prediction, both cls and mask must be good at threshold
        is_mask_respect = ious >= iou_threshold
        is_true_positive = torch.bitwise_and(is_true_positive, is_mask_respect)
        mask_metric.update(confidences, is_true_positive, num_instances)

        if self._predict_height:
            ...
            # height_iou *= ious
            # is_mask_respect = height_iou >= iou_threshold
            # is_true_positive = torch.bitwise_and(is_true_positive, is_mask_respect)
            # height_metric.update(confidences, is_true_positive, num_instances)

        # mAP per level if applicable
        iou_threshold = 0.7
        if metadata is not None:
            assigns = \
                list(map(list, (map(get_sampling, cls_pred_score, masks_pred, all_gt_labels_list, all_gt_masks_list))))[
                    -1]

            for i, assign in enumerate(assigns):
                # difficulties = metadata[i]['difficulty']
                # difficulties_tensor = torch.tensor(difficulties, dtype=torch.long).to(assign.pos_inds.device)
                # d = torch.zeros_like(all_gt_labels_list[i])
                # d[all_gt_labels_list[i] > 0] = difficulties_tensor
                # difficulties_tensor = d
                # difficulties_tensor[i, assign.pos_inds] = difficulties_tensor[i, assign.pos_assigned_gt_inds]

                all_instances = set(np.unique(metadata[i]['mask'])) - {0}
                instances = list(all_instances)
                inst_tensor = torch.tensor(instances, dtype=torch.long).to(assign.pos_inds.device)
                a = torch.zeros_like(all_gt_labels_list[i])
                a[all_gt_labels_list[i] > 0] = inst_tensor
                inst_tensor = a
                inst_tensor[i, assign.pos_inds] = inst_tensor[i, assign.pos_assigned_gt_inds]

                for inst in all_instances:
                    diff_mask = inst_tensor == inst
                    idx_ = diff_mask[detection_idx]
                    conf_diff = confidences[idx_]
                    is_true_positive_diff = is_true_positive[idx_]
                    target_masks_inst, binary_pred_mask_inst = target_masks[idx_], binary_pred_mask[idx_]
                    mask_area_metric.update(target_masks_inst, binary_pred_mask_inst, inst)

                continue

                for j, diff in enumerate([Difficulty.Easy, Difficulty.Moderate, Difficulty.Hard]):
                    mask_metric = mAP_level[j]
                    diff_mask = difficulties_tensor == diff
                    conf_diff = confidences[diff_mask[detection_idx]]
                    is_true_positive_diff = is_true_positive[diff_mask[detection_idx]]
                    num_instances_diff = diff_mask.sum()
                    mask_metric.update(conf_diff, is_true_positive_diff, num_instances_diff)

        for i, iou_threshold in enumerate([0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]):
            num_instances = (label_gt == cls).sum()
            pred_scores = cls_pred_score[-1]
            pred_cls = pred_scores.argmax(dim=-1)
            detection_idx = torch.where(pred_cls == cls)

            confidences = pred_scores[detection_idx][:, cls]
            y_true_for_detection = torch.stack(labels_list[-1])[detection_idx]
            is_true_positive = (y_true_for_detection == cls).long()

            target_masks = torch.stack(mask_targets_list[-1])[detection_idx].long()

            target_shape = target_masks.shape[-2:]
            pred_masks = masks_pred[-1][detection_idx]
            pred_masks = F.interpolate(
                pred_masks.unsqueeze(1),
                target_shape,
                mode='bilinear',
                align_corners=False).squeeze(1)
            binary_pred_mask = torch.sigmoid(pred_masks) > 0.5

            if use_rot_iou:
                ious = rot_mask_iou(target_masks, binary_pred_mask)
            else:
                ious = batched_mask_iou(target_masks, binary_pred_mask)
            mIoU_metric.update(ious)
            return

            for mask_idx in range(target_masks.shape[0]):
                m1, m2 = target_masks[i].cpu().numpy(), pred_masks[i].cpu().numpy()

                m1 = m1.astype(np.uint8)
                m2 = m2.astype(np.uint8)

                cnt1, _ = cv2.findContours(m1, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                cnt2, _ = cv2.findContours(m2, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

                if len(cnt1) == 0 or len(cnt2) == 0:
                    ious.append(0.0)
                    continue

                cnt1 = max(cnt1, key=lambda c: cv2.contourArea(c))
                cnt2 = max(cnt2, key=lambda c: cv2.contourArea(c))

                rect1 = cv2.minAreaRect(cnt1)
                rect2 = cv2.minAreaRect(cnt2)

            # Do bitwise and on prediction, both cls and mask must be good at threshold
            is_mask_respect = ious >= iou_threshold
            is_true_positive = torch.bitwise_and(is_true_positive, is_mask_respect)
            all_metric[i].update(confidences, is_true_positive, num_instances)

    def _compute_point_mIoU(self):
        ...

    def _get_config(self, num_things_classes, num_stuff_classes, num_queries, in_channels, head_feat_channels,
                    head_out_channels, reverse_class_weights):
        num_classes = num_things_classes + num_stuff_classes
        class_weights = [1.0] * num_classes + [0.1]
        if reverse_class_weights:
            class_weights = list(reversed(class_weights))

        num_transformer_feat_level = 3
        num_heads = 8

        return Config(dict(
            in_channels=in_channels,  # pass to pixel_decoder inside
            strides=[4, 8, 16, 32],
            feat_channels=head_feat_channels,
            out_channels=head_out_channels,
            num_things_classes=num_things_classes,
            num_stuff_classes=num_stuff_classes,
            num_queries=num_queries,
            num_transformer_feat_level=num_transformer_feat_level,
            pixel_decoder=dict(
                type='MSDeformAttnPixelDecoder',
                num_outs=num_transformer_feat_level,
                norm_cfg=dict(type='GN', num_groups=32),
                act_cfg=dict(type='ReLU'),
                encoder=dict(
                    type='DetrTransformerEncoder',
                    num_layers=6,
                    transformerlayers=dict(
                        type='BaseTransformerLayer',
                        attn_cfgs=dict(
                            type='MultiScaleDeformableAttention',
                            embed_dims=head_feat_channels,
                            num_heads=num_heads,
                            num_levels=num_transformer_feat_level,
                            num_points=4,
                            im2col_step=64,
                            dropout=0.0,
                            batch_first=False,
                            norm_cfg=None,
                            init_cfg=None),
                        ffn_cfgs=dict(
                            type='FFN',
                            embed_dims=head_feat_channels,
                            feedforward_channels=1024,
                            num_fcs=2,
                            ffn_drop=0.0,
                            act_cfg=dict(type='ReLU', inplace=True)),
                        operation_order=('self_attn', 'norm', 'ffn', 'norm')),
                    init_cfg=None),
                positional_encoding=dict(
                    type='SinePositionalEncoding', num_feats=head_feat_channels // 2, normalize=True),
                init_cfg=None),
            enforce_decoder_input_project=False,
            positional_encoding=dict(
                type='SinePositionalEncoding', num_feats=head_feat_channels // 2, normalize=True),
            transformer_decoder=dict(
                type='DetrTransformerDecoder',
                return_intermediate=True,
                num_layers=9,
                transformerlayers=dict(
                    type='DetrTransformerDecoderLayer',
                    attn_cfgs=dict(
                        type='MultiheadAttention',
                        embed_dims=head_feat_channels,
                        num_heads=num_heads,
                        attn_drop=0.0,
                        proj_drop=0.0,
                        dropout_layer=None,
                        batch_first=False),
                    ffn_cfgs=dict(
                        embed_dims=head_feat_channels,
                        feedforward_channels=2048,
                        num_fcs=2,
                        act_cfg=dict(type='ReLU', inplace=True),
                        ffn_drop=0.0,
                        dropout_layer=None,
                        add_identity=True),
                    feedforward_channels=2048,
                    operation_order=('cross_attn', 'norm', 'self_attn', 'norm',
                                     'ffn', 'norm')),
                init_cfg=None),
            loss_cls=dict(
                type='CrossEntropyLoss',
                use_sigmoid=False,
                loss_weight=2.0,
                reduction='mean',
                class_weight=class_weights),
            loss_height=dict(
                type='CrossEntropyLoss',
                use_sigmoid=False,
                loss_weight=2.0,
                reduction='mean'),
            loss_mask=dict(
                type='CrossEntropyLoss',
                use_sigmoid=True,
                reduction='mean',
                loss_weight=5.0),
            loss_dice=dict(
                type='DiceLoss',
                use_sigmoid=True,
                activate=True,
                reduction='mean',
                naive_dice=True,
                eps=1.0,
                loss_weight=5.0)),
            train_cfg=dict(
                num_points=12544,
                oversample_ratio=3.0,
                importance_sample_ratio=0.75,
                assigner=dict(
                    type='MaskHungarianAssigner',
                    cls_cost=dict(type='ClassificationCost', weight=2.0),
                    mask_cost=dict(
                        type='CrossEntropyLossCost', weight=5.0, use_sigmoid=True),
                    dice_cost=dict(
                        type='DiceCost', weight=5.0, pred_act=True, eps=1.0)),
                sampler=dict(type='MaskPseudoSampler')),
            # test_cfg=dict(
            #     panoptic_on=True,
            #     # For now, the dataset does not support
            #     # evaluating semantic segmentation metric.
            #     semantic_on=False,
            #     instance_on=True,
            #     # max_per_image is for instance segmentation.
            #     max_per_image=100,
            #     iou_thr=0.8,
            #     # In Mask2Former's panoptic postprocessing,
            #     # it will filter mask area where score is less than 0.5 .
            #     filter_low_score=True)
        )
